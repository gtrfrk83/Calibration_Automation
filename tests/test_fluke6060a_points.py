"""Fluke 6060A performance verification: the spec, the engine on the simulated bench (6060A + 8902A + 8563E + 96270A power meter + a 33220A as the LF source).

* Spec: counts per test, JSON equals the builder's output, every point has a page reference, the printed typos are flagged (never corrected silently), limits judged in Decimal with the
  manual's strict "<" where it prints one, the section-error / sum formulas.
* Engine (the real App on the simulated bench, tests/live_editor_harness.py): every test group passes, RF is off after each point and after a failure, a failed read-back is loud and the
  write is not repeated, THD at 10 kHz is typed (and can be switched off), a typed reading is judged by the engine, the power-on test, demo mode is synthetic.
Nothing here has run on a real 6060A, and the simulators are not facts about the instruments: see the UNVERIFIED flags on the points.
"""
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402  (installs the tkinter stub)

import fluke6060a_verification as E  # noqa: E402
import manual_override  # noqa: E402
from drivers.base import InstrumentError  # noqa: E402
from drivers.simulated_6060a import make_rf_bench, rf_state  # noqa: E402
from drivers.simulated_96270a import make_pm_transport  # noqa: E402
from drivers.simulated_fgen import FgenBench, SimGen  # noqa: E402

SPEC = json.loads((ROOT / 'specs' / 'fluke_6060a_pv.json').read_text(encoding='utf-8'))


def points():
    return [p for s in SPEC['sections'] for p in s['points']]


def by_ref(ref):
    return next(p for p in points() if p['ref'] == ref)


def builder():
    spec = importlib.util.spec_from_file_location('build_fluke_6060a_spec', ROOT / 'specs' / 'build_fluke_6060a_spec.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SpecTests(unittest.TestCase):
    def test_counts_and_groups(self):
        got = {s['id']: len(s['points']) for s in SPEC['sections']}
        self.assertEqual(got, {'4A-3': 1, '4A-4': 9, '4A-5': 96, '4A-6': 40, '4A-7': 5, '4A-8': 144, '4A-11': 20, 'T1': 2, 'T2': 2, 'T3': 44, 'T4': 1, 'T5': 1, 'T6': 70, 'T7': 1, 'T8': 34})
        self.assertEqual(len(points()), 470)
        self.assertEqual({p['group'] for p in points()}, {'POWERON', 'RX', 'RXPWR', 'PM', 'SA', 'EXT1K', 'EXT10K', 'EXT400'})

    def test_json_is_what_the_builder_makes(self):
        self.assertEqual(json.loads(json.dumps(builder().build_spec())), SPEC)

    def test_every_point_carries_a_page_reference_and_a_limit(self):
        for p in points():
            self.assertTrue(p.get('page'), p['ref'])
            self.assertLessEqual(p['low'], p['high'], p['ref'])
        self.assertEqual(len({p['ref'] for p in points()}), len(points()), 'refs are unique')

    def test_leakage_tests_are_not_built(self):
        self.assertFalse([p for p in points() if p['ref'].startswith(('4A-9', '4A-10'))])

    def test_mid_low_frequencies_are_the_named_constant(self):
        self.assertEqual(tuple(SPEC['constants']['mid_low_freqs_mhz']), builder().MID_LOW_FREQS_MHZ)
        self.assertEqual(builder().MID_LOW_FREQS_MHZ, (120, 244, 245, 850, 1050))
        freqs = {p['gen']['freq_mhz'] for s in SPEC['sections'] if s['id'] in ('4A-6', '4A-7') for p in s['points']}
        self.assertEqual(freqs, {120, 244, 245, 850, 1050})

    def test_synthesis_points_are_n_times_111_1111_with_a_ten_hz_window(self):
        pts = [p for s in SPEC['sections'] if s['id'] == '4A-4' for p in s['points']]
        self.assertEqual([round(p['gen']['freq_mhz'], 4) for p in pts], [round(n * 111.1111, 4) for n in range(1, 10)])
        for p in pts:
            self.assertEqual((p['high'] - p['nominal'], p['nominal'] - p['low']), (10.0, 10.0))
        self.assertTrue(any('owner confirmed' in f for f in pts[0]['flags']), 'the 10 Hz count is owner-confirmed, no longer UNVERIFIED')
        self.assertFalse(any('one count' in f and 'UNVERIFIED' in f for f in pts[0]['flags']))

    def test_printed_typos_are_flagged_not_corrected(self):
        text = json.dumps(SPEC['discrepancies'])
        for needle in ('Figure 4A-3', '245 kHz', '4 MHz', '30 MHz'):
            self.assertIn(needle, text)

    def test_harmonic_and_spur_limits_are_strict(self):
        for s in SPEC['sections']:
            if s['id'] == '4A-11':
                for p in s['points']:
                    self.assertTrue(p.get('strict_high'), p['ref'])
        self.assertEqual(by_ref('4A-11 harmonics 0.4 MHz')['high'], -30)

    def test_the_high_level_limit_is_one_and_a_half_db_for_every_section_and_sum(self):
        for p in points():
            if p['ref'].startswith('4A-5'):
                self.assertEqual((p['nominal'] - p['low'], p['high'] - p['nominal']) if p['meas'] != 'derived' else (1.5, 1.5), (1.5, 1.5), p['ref'])


class MidLevelOnThe8902A(unittest.TestCase):
    def test_4a6_is_measured_with_the_8902a_tuned_level(self):
        """Owner, 2026-10-29: the NRP40T (thermal, -35 to +20 dBm) cannot reach -66 dBm; 4A-6 uses the 8902A tuned RF level like 4A-7 / 4A-8. 4A-5 stays on the power meter."""
        mid = [p for p in points() if p["ref"].startswith("4A-6")]
        high = [p for p in points() if p["ref"].startswith("4A-5") and p.get("meas") == "level_pm"]
        self.assertEqual(len(mid), 40)
        self.assertTrue(all(p['meas'] == 'level_rx' and p['rx']['mode'] == 'tuned' for p in mid))
        self.assertEqual(len(high), 48)
        self.assertTrue(any('DEVIATION' in f for p in mid for f in p.get('flags', ())))


class JudgeAndDerive(unittest.TestCase):
    def test_judge_is_decimal_and_includes_its_limits(self):
        p = {'low': 0.1, 'high': 0.3}
        self.assertTrue(E.judge(p, 0.1))
        self.assertTrue(E.judge(p, 0.3))
        self.assertFalse(E.judge(p, 0.3000001))
        self.assertFalse(E.judge(p, 0.0999999))

    def test_strict_limit_fails_on_the_limit(self):
        p = {'low': -200, 'high': -30, 'strict_high': True}
        self.assertTrue(E.judge(p, -30.01))
        self.assertFalse(E.judge(p, -30.0))

    def test_section_error_and_sum_follow_the_manual_formulas(self):
        # M0 = 12.00; section n reads M0 - att(n) + e(n): the error is what is left over
        att = [0, 6, 12, 24, 24, 24, 24, 24]
        errs = [0, 0.10, -0.20, 0.30, 0.0, 0.05, -0.15, 0.25]
        refs = [f's{n}' for n in range(8)]
        readings = {refs[n]: 12.0 - att[n] + errs[n] for n in range(8)}
        readings['s0'] = 12.0
        sec = {'derive': {'kind': 'section', 'inputs': ['s0', 's2'], 'constant': 12}}
        self.assertAlmostEqual(E.derived_value(sec, readings), -0.20, places=9)
        total = {'derive': {'kind': 'sum', 'inputs': refs, 'level0': 12, 'attenuation': att}}
        self.assertAlmostEqual(E.derived_value(total, readings), sum(errs[1:]), places=9)
        self.assertIsNone(E.derived_value(total, {'s0': 12.0}), 'not all inputs read yet')

    def test_spec_derive_blocks_use_the_manual_attenuation_and_twelve_dbm(self):
        for p in points():
            d = p.get('derive')
            if d and d['kind'] == 'sum':
                self.assertEqual((d['level0'], d['attenuation']), (12, [0, 6, 12, 24, 24, 24, 24, 24]), p['ref'])
                self.assertEqual(len(d['inputs']), 8)


class Bench(unittest.TestCase):
    """The real App on the simulated bench."""
    DEMO = False

    def setUp(self):
        self.h = H.EngineHarness().start(E)
        self.addCleanup(self.h.stop) if hasattr(self.h, 'stop') else None
        p = mock.patch('time.sleep', side_effect=lambda s: None); p.start(); self.addCleanup(p.stop)
        E.configure()
        self.app = E.App(self.h.root, '6060A', demo=self.DEMO)
        self.h.app = self.app
        self.app.asset.set('A-6060'); self.app.serial.set('SN')
        self.app.mo_ask = lambda prompt, **k: manual_override.parse_reading(prompt, '0.5')
        self.typed = []
        self.bench, self.t6, self.t8902, self.t8563 = make_rf_bench()
        self.t8902.external_ref = True
        self.t8902.errors['freq_ppm'] = 0.005
        self.pm = make_pm_transport(self.bench)
        fb = FgenBench('33220A')
        self.lf = SimGen(fb)

        def operator(title, heading, steps, facts):
            self.t8902.sensor_on_calibrator = title.startswith('Calibrate the 8902A RF power')
            return True
        self.h.on_confirm = operator

    def connect(self, lf=True, lf_model='Keysight 33220A', **tr):
        self.app.lf_model.set(lf_model if lf else E.NO_LF)
        trs = dict(gen=self.t6, rx=self.t8902, sa=self.t8563, pm=self.pm)
        if lf:
            trs['lf'] = self.lf
        trs.update(tr)
        trs = {k: v for k, v in trs.items() if v is not None}
        self.app.io = E.IO(dict(uut='2'), self.app.lf_model.get(), transports=trs, mods=self.app.pm_state)
        st = self.app.pm_state
        st.store, st.devmode = self.h.env.store, self.h.env.dm
        self.app.on_options(save=False)
        return self.app.io

    def run_points(self, *prefixes, refs=None, seconds=300, connect=True):
        if connect and self.app.io is None:
            self.connect()
        pts = [p for p in self.app.active_points() if (refs and p['ref'] in refs) or (prefixes and p['ref'].startswith(prefixes))]
        self.rf_at_record = []
        orig = self.app._record

        def spy(p, reading, synthetic, **k):
            self.rf_at_record.append((p['ref'], rf_state(self.bench)['rf_on'], self.lf_on()))
            return orig(p, reading, synthetic, **k)
        self.app._record = spy
        self.app.execute(pts)
        self.assertTrue(self.h.pump(seconds))
        return pts

    def lf_on(self):
        try:
            return bool(self.lf.query('OUTP?').strip() in ('1', 'ON'))
        except Exception:
            return None

    def errors(self):
        return [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'showerror']

    def non_pass(self):
        return [(E.POINTS[int(k) - 1]['ref'], r['reading'], r['result']) for k, r in self.app.found.items() if r['result'] != 'PASS']

    def assert_clean(self, n=None):
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])
        if n is not None:
            self.assertEqual(len(self.app.found), n)
        self.assertFalse(rf_state(self.bench)['rf_on'], 'RF is off at the end')
        self.assertTrue(all(not on for _r, on, _lf in self.rf_at_record), 'RF was off whenever a point was recorded')


class Groups(Bench):
    def test_power_on_test_is_a_prompt_and_resets_afterwards(self):
        self.run_points('4A-3')
        self.assert_clean(1)
        self.assertTrue(any('self test' in d[1].lower() for d in self.h.dialogs if d[0] == 'confirm'))

    def test_synthesis_with_the_8902a(self):
        self.run_points('4A-4')
        self.assert_clean(9)

    def test_high_level_with_the_power_meter_and_the_derived_errors(self):
        pts = self.run_points('4A-5 0.4 MHz', '4A-5 1050 MHz')
        self.assert_clean(len(pts))
        self.assertEqual(self.pm.zero_with_rf_on and any(self.pm.zero_with_rf_on), False, 'the sensor is only zeroed with RF off')
        self.assertTrue(self.pm.zeroes >= 2)

    def test_mid_and_low_levels(self):
        pts = self.run_points('4A-6 120 MHz', '4A-7')
        self.assert_clean(len(pts))

    def test_alternate_levels_both_receiver_ranges(self):
        pts = self.run_points('4A-8 120 MHz', '4A-8 1050 MHz')
        self.assert_clean(len(pts))

    def test_harmonics_and_spurs_with_the_analyzer(self):
        self.run_points('4A-11')
        self.assert_clean(20)

    def test_external_and_internal_modulation_tests(self):
        pts = self.run_points('4A-12 test 1', '4A-12 test 2', '4A-12 test 3', '4A-12 test 4', '4A-12 test 5', '4A-12 test 7', '4A-12 test 8')
        self.assertTrue(pts)
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])
        self.assertTrue(all(lf is False for _r, _on, lf in self.rf_at_record), 'the LF generator output is off after every point')

    def test_the_whole_procedure_passes_on_the_simulated_bench(self):
        self.connect()
        self.app.execute(self.app.active_points())
        self.assertTrue(self.h.pump(600))
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])
        self.assertEqual(len(self.app.found), len(self.app.active_points()))
        self.assertFalse(rf_state(self.bench)['rf_on'])

    def test_the_reset_comes_before_the_first_point(self):
        self.run_points('4A-4 #1', refs=['4A-4 #1'])
        sent = [t for t in self.t6.sent]
        self.assertTrue(any(s.startswith('RC98') or 'RC98' in s for s in sent))
        first_freq = next(i for i, s in enumerate(sent) if re.match(r'\s*FR', s))
        self.assertLess(next(i for i, s in enumerate(sent) if 'RC98' in s), first_freq)


class Failures(Bench):
    def test_an_out_of_limit_reading_fails(self):
        self.t8902.errors['freq_ppm'] = 50.0            # 111 MHz x 50 ppm = 5.6 kHz: far outside +/- 10 Hz
        self.run_points(refs=['4A-4 #1'])
        self.assertEqual([r for _ref, _v, r in self.non_pass()], ['FAIL'])
        self.assertFalse(rf_state(self.bench)['rf_on'])

    def test_a_failed_read_back_stops_the_run_loudly_with_rf_off_and_is_not_retried(self):
        connect = self.connect()
        handle = self.t6.handle
        writes = []

        def drop_frequency(text):
            if re.match(r'\s*FR', text):
                writes.append(text)
                return None                              # the unit "accepts" the write but does not change
            return handle(text)
        self.t6.handle = drop_frequency
        self.run_points(refs=['4A-4 #2'])
        self.assertEqual(len(writes), 1, 'a failed write is never repeated')
        self.assertEqual(len(self.errors()), 1)
        self.assertEqual(self.app.found, {})
        self.assertFalse(rf_state(self.bench)['rf_on'])
        self.assertIs(connect, self.app.io)

    def test_a_reading_that_fails_offers_a_typed_reading_which_the_engine_judges(self):
        self.connect()
        self.t8902.fail_next = None
        calls = []

        def broken(*a, **k):
            raise InstrumentError('8902A: no reading')
        self.app.io.sa.measure_fundamental = broken
        self.app.mo_ask = lambda p, **k: calls.append(p['ref']) or manual_override.parse_reading(p, '-10')
        self.run_points(refs=['4A-11 harmonics 0.4 MHz'])
        self.assertEqual(calls, ['4A-11 harmonics 0.4 MHz'])
        rec = next(iter(self.app.found.values()))
        self.assertEqual(rec['result'], 'FAIL', 'a typed -10 dBc is judged by the engine against the < -30 dBc limit')
        self.assertFalse(rf_state(self.bench)['rf_on'])
        self.assertTrue(rec['overridden'])

    def test_a_power_on_failure_is_recorded_as_a_fail(self):
        self.connect()
        real = E.port.ask_yes_no
        with mock.patch.object(E.port, 'ask_yes_no', side_effect=lambda title, *a, **k: False if title == 'Power-on self test' else real(title, *a, **k)):
            self.run_points('4A-3')
        self.assertEqual([r for _ref, _v, r in self.non_pass()], ['FAIL'])


class Options(Bench):
    def test_there_is_no_option_651_handling_and_the_standard_deviation_points_are_all_kept(self):
        for p in E.POINTS:
            self.assertFalse(p.get('limits_651') or p.get('skip_if_651'), p['ref'])
            self.assertEqual(p['unavailable'], '' if not p.get('typed_only') else p['unavailable'])
        for ref in ('4A-12 test 6 deviation 9.99 kHz', '4A-12 test 6 deviation 0.999 kHz', '4A-12 test 7'):
            self.assertEqual(by_ref(ref)['ref'], ref)
        self.assertTrue(all(p['gen']['fm']['khz'] == 99.9 for p in E.POINTS if p['ref'].startswith('4A-12 test 6 ') and p['meas'] == 'fm_dev' and 'deviation' not in p['ref']))
        src = (ROOT / 'fluke6060a_verification.py').read_text(encoding='utf-8') + (ROOT / 'specs' / 'build_fluke_6060a_spec.py').read_text(encoding='utf-8')
        self.assertNotRegex(src, r'651|low_rate')

    def test_thd_at_10_khz_is_typed_with_rf_on_then_off(self):
        self.connect()
        asked = []

        def ask(p, **k):
            asked.append((p['ref'], rf_state(self.bench)['rf_on']))
            return manual_override.parse_reading(p, '0.5')
        self.app.mo_ask = ask
        self.run_points(refs=['4A-12 test 6 up 245 MHz THD'])
        self.assertEqual(asked, [('4A-12 test 6 up 245 MHz THD', True)])
        self.assertFalse(rf_state(self.bench)['rf_on'])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])

    def test_the_thd_box_off_removes_those_points(self):
        self.connect()
        self.app.thd_typed.set(False)
        self.app.on_options(save=False)
        thd = [p for p in E.POINTS if p.get('typed_only')]
        self.assertTrue(thd and all(p['unavailable'] for p in thd))
        self.assertFalse([p for p in self.app.active_points() if p.get('typed_only')])
        self.app.thd_typed.set(True)
        self.app.on_options(save=False)

    def test_no_lf_generator_selected_asks_the_operator(self):
        self.connect(lf=False)
        self.run_points(refs=['4A-12 test 1 #1'] if any(p['ref'] == '4A-12 test 1 #1' for p in E.POINTS) else [p['ref'] for p in E.POINTS if p['group'] == 'EXT1K'][:1])
        self.assertTrue(any('generator' in ' '.join(d[3]).lower() or 'generator' in d[1].lower() for d in self.h.dialogs if d[0] == 'confirm'))


class DemoAndReport(Bench):
    DEMO = True

    def test_demo_mode_records_only_synthetic_marked_data(self):
        pts = [p for p in self.app.active_points() if p['group'] != 'POWERON'][:12]
        self.app.execute(pts)
        self.assertTrue(self.h.pump(60))
        self.assertTrue(self.app.found)
        self.assertTrue(all(r['synthetic'] for r in self.app.found.values()))
        self.assertTrue(self.app.any_synthetic())
        self.assertIsNone(self.app.io, 'no instrument is opened in demo mode')

    def test_report_rows_and_the_asset_date_file_name(self):
        self.app.execute([p for p in self.app.active_points() if p['group'] == 'RX'][:3])
        self.assertTrue(self.h.pump(60))
        rows, pts = self.app.certificate_rows_and_points()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(pts), 3)
        import ui_theme_core as U
        name = U.report_filename('A-6060') if hasattr(U, 'report_filename') else None
        if name is not None:
            self.assertRegex(name, r'^A-6060-\d{4}-\d{2}-\d{2}\.pdf$|^A-6060-.*\.pdf$')


class SourceGuards(unittest.TestCase):
    ENGINE = (ROOT / 'fluke6060a_verification.py').read_text(encoding='utf-8')

    def test_manual_override_is_on_for_this_engine_only_by_its_own_flag(self):
        self.assertIs(E.App.MANUAL_OVERRIDE, True)
        self.assertRegex(self.ENGINE, re.compile(r'^\s*MANUAL_OVERRIDE\s*=\s*True', re.M))

    def test_no_write_is_retried_and_no_password_is_logged(self):
        self.assertNotRegex(self.ENGINE, r'query_retry')
        self.assertNotRegex(self.ENGINE.lower(), r'password|passwd')

    def test_addresses_are_not_hard_coded_in_the_engine(self):
        lines = [ln for ln in self.ENGINE.splitlines() if re.search(r'GPIB0::\d+::INSTR', ln) and not ln.startswith('DEFAULT_RF_ADDR') and 'such as' not in ln and 'GPIB0::4' not in ln[:0]]
        lines = [ln for ln in lines if 'GPIB0::4::INSTR' not in ln and 'passes through' not in ln]      # the docstring example and the editable 96270A default
        self.assertEqual(lines, [])
        for name in ('uut_addr', 'rx_addr', 'sa_addr', 'rf_addr', 'lf_addr'):
            self.assertIn(name, self.ENGINE)

    def test_the_limits_are_not_rewritten_in_the_engine(self):
        self.assertNotRegex(self.ENGINE, r"\['(low|high|nominal)'\]\s*=\s*[-\d]")

    def test_launcher_and_sidecar(self):
        side = json.loads((ROOT / 'Procedures' / 'Fluke_6060A_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((side['id'], side['model'], side['launcher']), ('Fluke_6060A_Verification', '6060A', 'Procedures/Fluke_6060A_Verification.py'))
        self.assertIn('specs/fluke_6060a_pv.json', side['specs'])
        self.assertIn('fluke6060a_verification.py', side['engine'])
        self.assertTrue((ROOT / 'Procedures' / 'Fluke_6060A_Verification.py').is_file())
        self.assertTrue((ROOT / 'diagrams' / 'README_6060a.txt').is_file())

    def test_the_qt_view_has_the_five_address_boxes(self):
        src = (ROOT / 'fluke6060a_view_qt.py').read_text(encoding='utf-8')
        for name in ('uut_addr', 'rx_addr', 'sa_addr', 'rf_addr', 'lf_addr'):
            self.assertIn(f'self.{name}', src)


if __name__ == '__main__':
    unittest.main()


class FrequencyRange(Bench):
    """Owner, 2026-10-29: this lab's 6060A only reaches 520 MHz. Points above the chosen range are not run and are kept on the report as NOT TESTED."""

    def test_the_520_mhz_range_leaves_the_upper_points_out_and_reports_them(self):
        self.assertEqual(self.app.max_mhz(), 1050.0)                              # the manual's range by default
        self.assertFalse(any(p.get('not_tested') for p in E.POINTS))
        self.app.freq_range.set('0.1 to 520 MHz')
        self.app.on_options(save=False)
        out = [p for p in E.POINTS if p.get('not_tested')]
        self.assertTrue(out)
        for p in E.POINTS:
            f = E.uut_mhz(p, {q['ref']: q for q in E.POINTS})
            self.assertEqual(bool(p.get('not_tested')), f is not None and f > 520, p['ref'])
        self.assertTrue(all(not self.app.active(p) and '520 MHz' in p['unavailable'] for p in out))
        self.assertEqual(len([p for p in out if p['ref'].startswith('4A-4')]), 5)          # 555.5555 to 999.9999 MHz
        self.assertTrue(any(p['ref'].startswith('4A-5') and p['meas'] == 'derived' for p in out), 'the 850 / 1050 MHz section errors and sums go too')
        self.assertFalse(any(p['ref'].startswith('4A-11') and (p.get('gen') or {}).get('freq_mhz', 0) <= 520 for p in out))
        rows, pts = self.app.certificate_rows_and_points()
        nt = [r for r, p in zip(rows, pts) if p.get('not_tested')]
        self.assertEqual(len(nt), len(out))
        self.assertTrue(all('NOT TESTED' in r['Description'] and r['As Found'] == '' and r['As Left'] == '' for r in nt))

    def test_a_520_mhz_run_never_programs_the_generator_above_520_mhz(self):
        self.app.freq_range.set('0.1 to 520 MHz')
        self.connect()
        sent = []
        orig = self.t6.write
        self.t6.write = lambda text: (sent.append(text), orig(text))[1]
        self.run_points('4A-4')
        import re
        freqs = [float(m.group(1)) for t in sent for m in re.finditer(r'FR([\d.]+)MZ', t)]
        self.assertTrue(freqs)
        self.assertLessEqual(max(freqs), 520.0)
        self.assertEqual(len(self.app.found), 4)                                   # 111.1111 to 444.4444 MHz
