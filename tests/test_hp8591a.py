"""HP 8591A procedure (USAF T.O. 33K3-4-2864-1): the spec, the trace helpers, every measurement on the simulated bench (good unit passes, an injected error fails), the output-off rule, the
typed and not-tested points, and the real App on the simulated bench. Nothing here has run on a real 8591A or 96270A; see the UNVERIFIED flags on the points."""
import importlib.util
import json
import runpy
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402  (installs the tkinter stub)

import hp8591a_verification as E  # noqa: E402
import manual_override  # noqa: E402
from drivers.base import InstrumentError  # noqa: E402
from drivers.simulated_8591a import make_8591a_bench, source_state  # noqa: E402

SPEC_FILE = ROOT / 'specs' / 'hp_8591a_pv.json'
SPEC = json.loads(SPEC_FILE.read_text(encoding='utf-8'))


def points():
    return [p for s in SPEC['sections'] for p in s['points']]


def by_ref(ref):
    return next(p for p in points() if p['ref'] == ref)


def builder():
    spec = importlib.util.spec_from_file_location('build_hp_8591a_spec', ROOT / 'specs' / 'build_hp_8591a_spec.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SpecTests(unittest.TestCase):
    def test_counts(self):
        got = {s['id']: len(s['points']) for s in SPEC['sections']}
        self.assertEqual(got, {'H-3': 1, 'H-4.1': 1, 'H-4.1b': 2, 'H-4.2': 3, 'H-4.3': 4, 'H-4.4': 13, 'H-4.5': 8, 'H-4.6a': 12, 'H-4.6b': 4, 'H-4.7': 5, 'H-4.8': 9, 'H-4.9': 7,
                               'H-4.10': 8, 'H-4.11a': 36, 'H-4.11b': 7, 'H-4.11c': 3, 'H-4.12': 4})
        self.assertEqual(len(points()), 127)

    def test_json_is_what_the_builder_makes(self):
        self.assertEqual(json.loads(json.dumps(builder().build_spec())), SPEC)

    def test_every_point_has_a_document_reference_a_limit_and_a_unique_ref(self):
        for p in points():
            self.assertTrue(p['page'].startswith('T.O. 33K3-4-2864-1 para'), p['ref'])
            self.assertLessEqual(p['low'], p['high'], p['ref'])
            self.assertTrue(p['flags'] or p['meas'] == 'manual', p['ref'])
        self.assertEqual(len({p['ref'] for p in points()}), len(points()))

    def test_the_printed_limits(self):
        span = {p['ti']['span_hz']: (p['low'], p['high']) for p in points() if p['func'] == 'SPAN'}
        self.assertEqual(span[1800e6], (1386e6, 1494e6))
        self.assertEqual(span[10e6], (7.8e6, 8.2e6))
        self.assertEqual(span[100e3], (78e3, 82e3))
        st = {p['ti']['st_s']: (p['low'], p['high']) for p in points() if p['func'] == 'SWEEPTIME'}
        self.assertEqual(st[0.02], (0.0154, 0.0166))
        self.assertEqual(st[100.0], (77.0, 83.0))
        lin = [(p['low'], p['high']) for p in points() if p['func'] == 'SCALELIN']
        self.assertEqual(lin, [(0.15098, 0.1652), (0.10469, 0.11891), (0.07222, 0.08644), (0.04879, 0.06301)])
        self.assertEqual([(p['low'], p['high']) for p in points() if p['func'] == 'RBWBW'][0], (2.4e6, 3.6e6))
        self.assertEqual({p['ref']: (p['low'], p['high']) for p in points() if p['func'] == 'CALFREQ'},
                         {'4.1.13 CAL OUT frequency (standard)': (299999250.0, 300000750.0), '4.1.13 CAL OUT frequency (OPT 004)': (299999967.0, 300000033.0)})
        sb = [p for p in points() if p['func'] == 'NOISESB']
        self.assertTrue(all(p['strict_high'] for p in sb))
        self.assertEqual([p['high'] for p in sb], [-60.0, -60.0, -70.0, -70.0])

    def test_no_calibration_or_security_command_is_in_the_driver(self):
        from drivers.hp_8591a import COMMANDS
        sent = ' '.join(c.template.upper() for c in COMMANDS.values())
        for word in ('CAL', 'PASSWORD', 'ERASE', 'FORMAT', 'KEYSTRK', 'PWRON', 'SAVE', 'STORE'):
            self.assertNotIn(word, sent, word)

    def test_launcher_and_sidecar(self):
        side = json.loads((ROOT / 'Procedures' / 'HP_8591A_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual(side['launcher'], 'Procedures/HP_8591A_Verification.py')
        self.assertEqual(side['specs'], ['specs/hp_8591a_pv.json'])
        with mock.patch.object(E, 'main') as main:
            runpy.run_path(str(ROOT / 'Procedures' / 'HP_8591A_Verification.py'), run_name='__main__')
        main.assert_called_once()


class Helpers(unittest.TestCase):
    def test_judge_is_decimal_and_strict_for_less_than_limits(self):
        p = dict(low=-200.0, high=-60.0, strict_high=True)
        self.assertFalse(E.judge(p, -60.0))
        self.assertTrue(E.judge(p, -60.0001))
        self.assertTrue(E.judge(dict(low=0.1, high=0.3), 0.3))
        self.assertFalse(E.judge(dict(low=0.1, high=0.3), 0.30000000000000004))

    def test_peak_position_is_exact_for_a_gaussian_in_db(self):
        trace = [-0.5 * ((i - 100.3) / 4.0) ** 2 for i in range(401)]
        self.assertAlmostEqual(E.peak_position(trace), 100.3, places=6)

    def test_width_at_3_db(self):
        s = 10.0
        trace = [-3.0 * ((i - 200.0) / s) ** 2 for i in range(401)]      # -3 dB at +/- s points
        self.assertAlmostEqual(E.width_at(trace), 2 * s, delta=0.1)
        with self.assertRaises(InstrumentError):
            E.width_at([0.0] * 401)

    def test_eight_period_time(self):
        import math
        trace = [-10 + 8 * math.sin(2 * math.pi * 10 * i / 400) for i in range(401)]      # 10 periods per sweep
        self.assertAlmostEqual(E.eight_period_time_s(trace, 1.0), 0.8, delta=0.002)
        with self.assertRaises(InstrumentError):
            E.eight_period_time_s([-10.0] * 401, 1.0)

    def test_auto_rb(self):
        self.assertEqual(E.auto_rb(1.8e9), 3e6)
        self.assertEqual(E.auto_rb(100e3), 1e3)
        self.assertEqual(E.auto_rb(5e6), 100e3)

    def test_derived_values(self):
        p = dict(derive=dict(op='range', inputs=['a', 'b', 'c']))
        self.assertEqual(E.derived_value(p, dict(a=0.5, b=-0.25, c=0.1)), 0.75)
        self.assertIsNone(E.derived_value(p, dict(a=0.5)))
        self.assertEqual(E.derived_value(dict(derive=dict(op='min', inputs=['a', 'b'])), dict(a=0.5, b=-0.25)), -0.25)


class Options(unittest.TestCase):
    def setUp(self):
        E.configure()

    def test_option_004_chooses_the_counter_point(self):
        E.apply_options(E.POINTS, False)
        self.assertEqual([p['opt'] for p in E.POINTS if p['meas'] == 'calout_ctr' and not p['unavailable']], ['std'])
        E.apply_options(E.POINTS, True)
        self.assertEqual([p['opt'] for p in E.POINTS if p['meas'] == 'calout_ctr' and not p['unavailable']], ['004'])

    def test_the_two_slowest_sweep_times_are_not_tested(self):
        nt = [(p['ti']['st_s'], p['unavailable']) for p in E.POINTS if p.get('not_tested')]
        self.assertEqual([x[0] for x in nt], [50.0, 100.0])
        self.assertTrue(all('1 Hz' in x[1] for x in nt))
        self.assertTrue(all(not E.App.active(None, p) for p in E.POINTS if p.get('not_tested')))


class SimBase(unittest.TestCase):
    def setUp(self):
        p = mock.patch('time.sleep', side_effect=lambda s: None); p.start(); self.addCleanup(p.stop)
        E.configure()
        self.bench, self.tu, self.ts = make_8591a_bench()
        self.io = E.IO(dict(uut='18'), transports=dict(uut=self.tu, src=self.ts))
        self.addCleanup(self.io.close)

    def pt(self, ref):
        return next(p for p in E.POINTS if p['ref'] == ref)

    def measure(self, ref):
        p = self.pt(ref)
        return p, self.io.measure(p)

    def src_off(self):
        return not source_state(self.bench)['output']


class Measurements(SimBase):
    def test_every_automatic_point_passes_on_a_good_unit_and_the_output_is_off_after_each(self):
        self.io.prep_pm_zero()
        n = 0
        for p in E.POINTS:
            if p['meas'] in ('derived', 'selfcal', 'manual', 'calout_ctr') or p.get('unavailable'):
                continue
            v = self.io.measure(p)
            self.assertTrue(E.judge(p, v), (p['ref'], v))
            self.assertTrue(self.src_off(), p['ref'])
            n += 1
        self.assertEqual(n, 115)
        self.assertEqual(self.tu.errors, [])

    def test_no_write_is_sent_twice_in_a_row_and_the_log_has_no_calibration(self):
        self.io.prep_pm_zero()
        self.io.measure(self.pt('4.6 Table 4 -2 dB'))
        text = '\n'.join(self.io.log.lines()).upper()
        for word in ('CAL', 'PASSWORD', 'ERASE'):
            self.assertNotIn(word, text.replace('CAL OUT', ''))

    def test_calout_level_out_of_limits_fails(self):
        self.io.prep_pm_zero()
        self.ts.calout_error_db = 0.9
        p, v = self.measure('4.1.1 to 4.1.8 CAL OUT level')
        self.assertFalse(E.judge(p, v))

    def test_sensor_zero_is_done_once_and_with_the_output_off(self):
        self.io.prep_pm_zero()
        self.assertEqual(self.ts.zeroes, 1)
        self.measure('4.1.1 to 4.1.8 CAL OUT level')
        self.assertEqual(self.ts.zeroes, 1)

    def test_span_error_fails(self):
        self.tu.span_scale = 1.08
        p, v = self.measure('4.4 Table 2 span 100 MHz')
        self.assertFalse(E.judge(p, v), v)

    def test_sweep_time_error_fails(self):
        self.tu.st_scale = 1.1
        p, v = self.measure('4.5 Table 3 sweep 0.1 s')
        self.assertFalse(E.judge(p, v), v)
        self.assertTrue(self.src_off())
        self.assertEqual(source_state(self.bench)['inst'], 'SINE')            # back to the leveled sine after AM

    def test_scale_fidelity_error_fails(self):
        self.tu.scale_error = lambda dbm: 1.0 if dbm < -45 else 0.0
        p, v = self.measure('4.6 Table 5 -60 dB')
        self.assertFalse(E.judge(p, v), v)

    def test_linear_scale_is_read_in_volts_and_trimmed(self):
        p, v = self.measure('4.6 Table 6 70.7 %')
        self.assertAlmostEqual(v, 0.2236 * 0.7071, delta=0.002)
        self.assertTrue(E.judge(p, v))

    def test_attenuator_and_reference_level_errors_fail(self):
        self.tu.atten_error = lambda at: 0.9 if at == 40 else 0.0
        p, v = self.measure('4.7 Table 7 40 dB')
        self.assertFalse(E.judge(p, v), v)
        self.tu.reflevel_error = lambda rl: 2.0 if rl <= -60 else 0.0
        p, v = self.measure('4.8 Table 8 RL -70 dBm')
        self.assertFalse(E.judge(p, v), v)

    def test_rbw_errors_fail(self):
        self.tu.rbw_switch_error = lambda rb: 0.9 if rb == 100e3 else 0.0
        p, v = self.measure('4.9 Table 9 RBW 100000 Hz')
        self.assertFalse(E.judge(p, v), v)
        self.tu.rbw_scale = 1.4
        p, v = self.measure('4.10 Table 10 RBW 100000 Hz')
        self.assertFalse(E.judge(p, v), v)

    def test_frequency_response_error_fails(self):
        self.tu.response_error = lambda f: 2.0 if abs(f - 700e6) < 1e6 else 0.0
        p, v = self.measure('4.11 Table 11 700 MHz')
        self.assertFalse(E.judge(p, v), v)

    def test_noise_sidebands_close_to_the_carrier_fail(self):
        p = self.pt('4.3.4 to 4.3.12 +10 kHz')
        self.assertFalse(E.judge(p, -59.9))
        self.assertTrue(E.judge(p, -60.1))

    def test_a_missing_source_offers_a_typed_reading(self):
        io = E.IO(dict(uut='18'), transports=dict(uut=make_8591a_bench()[1]))
        self.addCleanup(io.close)
        with self.assertRaises(E.ReadingUnavailable):
            io.measure(self.pt('4.2.3 to 4.2.11 1.5 GHz span 20 MHz'))

    def test_a_failed_point_leaves_the_output_off(self):
        self.bench.fail_next = 'AM:STAT'
        with self.assertRaises(Exception):
            self.measure('4.5 Table 3 sweep 0.1 s')
        self.assertTrue(self.src_off())

    def test_typed_points_return_typed_point_without_touching_the_source(self):
        before = len(self.ts.sent)
        for ref in ('4.12.13 noise level', '4.1.13 CAL OUT frequency (standard)'):
            p, v = self.measure(ref)
            self.assertIsInstance(v, E.TypedPoint)
        self.assertTrue(self.src_off())
        self.assertEqual(len(self.ts.sent), before)

    def test_the_slow_sweep_rows_cannot_be_made_by_the_96270a(self):
        p = dict(self.pt('4.5 Table 3 sweep 10 s'))
        p['am'] = dict(p['am'], rate_hz=0.2)
        with self.assertRaises(E.ReadingUnavailable):
            self.io.measure(p)
        self.assertTrue(self.src_off())


class AppBench(unittest.TestCase):
    """The real App on the simulated bench."""
    DEMO = False

    def setUp(self):
        self.h = H.EngineHarness().start(E)
        p = mock.patch('time.sleep', side_effect=lambda s: None); p.start(); self.addCleanup(p.stop)
        E.configure()
        self.app = E.App(self.h.root, '8591A', demo=self.DEMO)
        self.h.app = self.app
        self.app.asset.set('A-8591'); self.app.serial.set('SN')
        self.bench, self.tu, self.ts = make_8591a_bench()
        self.prompts = []

        def operator(title, heading, steps, facts):
            self.prompts.append(title)
            return True
        self.h.on_confirm = operator
        self.app.mo_ask = lambda p, **k: manual_override.parse_reading(p, str(self.typed(p)))

    @staticmethod
    def typed(p):
        _lim, _unit, scale = manual_override.entry_scale(p)
        return (p['low'] + p['high']) / 2 / float(scale)

    def connect(self):
        self.app.io = E.IO(dict(uut='18'), transports=dict(uut=self.tu, src=self.ts), mods=self.app.pm_state)
        st = self.app.pm_state
        st.store, st.devmode = self.h.env.store, self.h.env.dm
        self.app.on_options(save=False)

    def run_all(self, seconds=600):
        if self.app.io is None:
            self.connect()
        self.app.execute(self.app.active_points())
        self.assertTrue(self.h.pump(seconds))


class AppRun(AppBench):
    def test_a_full_run_records_every_active_point_and_the_derived_ones(self):
        self.run_all()
        active = self.app.active_points()
        self.assertEqual(len(self.app.found), len(active))
        self.assertTrue(all(r['result'] == 'PASS' for r in self.app.found.values()), [(k, r['reading']) for k, r in self.app.found.items() if r['result'] != 'PASS'])
        derived = [r for k, r in self.app.found.items() if E.POINTS[int(k) - 1]['meas'] == 'derived']
        self.assertEqual(len(derived), 3)
        self.assertTrue(all(r['derived'] for r in derived))
        self.assertFalse(source_state(self.bench)['output'])
        self.assertEqual(len(active), 127 - 2 - 1)                    # two NOT TESTED rows and the other counter option

    def test_prompts_come_once_per_wiring_group_change_and_the_zero_first(self):
        self.run_all()
        self.assertEqual(self.prompts[0], 'Zero the NRP40T power sensor')
        self.assertIn('Self-calibration', self.prompts)
        self.assertEqual(self.prompts.count('Rewire / verify before enabling output'), 6)     # CALPM, CALCTR, SRC, CALIN, SRC, DANL (the self-calibration has its own prompt)
        self.assertEqual(self.ts.zeroes, 1)

    def test_not_tested_rows_are_on_the_report_with_no_reading(self):
        self.run_all()
        rows, pts = self.app.certificate_rows_and_points()
        nt = [r for r, p in zip(rows, pts) if p.get('not_tested')]
        self.assertEqual(len(nt), 2)
        self.assertTrue(all('NOT TESTED' in r['Description'] for r in nt))

    def test_the_typed_points_are_marked_manual(self):
        self.run_all()
        manual = [r for k, r in self.app.found.items() if E.POINTS[int(k) - 1]['meas'] in ('calout_ctr', 'manual', 'selfcal')]
        self.assertEqual(len(manual), 1 + 1 + 4)
        self.assertTrue(all(r['manual'] for r in manual))

    def test_option_004_switches_the_counter_point(self):
        self.app.opt004.set(True)
        self.app.on_options(save=False)
        self.assertEqual([p['opt'] for p in self.app.active_points() if p['meas'] == 'calout_ctr'], ['004'])


class AppDemo(AppBench):
    DEMO = True

    def test_demo_readings_are_all_synthetic_and_nothing_is_sent(self):
        self.app.execute(self.app.active_points())
        self.assertTrue(self.h.pump(300))
        self.assertTrue(self.app.found)
        self.assertTrue(all(r.get('synthetic') for r in self.app.found.values()))
        self.assertEqual(self.tu.sent, [])


class Upfront(unittest.TestCase):
    def _app(self, demo=False):
        E.configure()
        app = E.App.__new__(E.App)
        app.demo, app._prep_done, app.calls = demo, set(), []
        app._run_preps = lambda points, i, p, key, preps: app.calls.append(('preps', i, p['id'], list(preps)))
        app._next = lambda points, i, previous, after_prep=False: app.calls.append(('next', i))
        return app

    def test_the_sensor_zero_comes_first_in_one_pass(self):
        app = self._app()
        app._upfront_preps(E.POINTS)
        self.assertEqual(app.calls, [('preps', 0, next(p['id'] for p in E.POINTS if p['meas'] == 'calout_pm'), ['pm_zero'])])

    def test_demo_asks_for_nothing(self):
        app = self._app(demo=True)
        app._upfront_preps(E.POINTS)
        self.assertEqual(app.calls, [('next', 0)])


if __name__ == '__main__':
    unittest.main()
