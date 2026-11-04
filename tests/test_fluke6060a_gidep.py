"""Fluke 6060A/AN procedure from the GIDEP document T.O. 33K3-4-911-1: the spec (counts, the printed tables' limits, JSON equals the builder) and the real App on the simulated bench
(the same engine as the Instruction Manual procedure, its own spec, settings key and launcher). Nothing here has run on a real 6060A; see the UNVERIFIED flags on the points."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import test_fluke6060a_points as T  # noqa: E402  (the simulated-bench harness; installs the tkinter stub)

import fluke6060a_verification as E  # noqa: E402
import manual_override  # noqa: E402
from drivers.simulated_6060a import rf_state  # noqa: E402

GIDEP_SPEC = ROOT / 'specs' / 'fluke_6060a_gidep_pv.json'
SPEC = json.loads(GIDEP_SPEC.read_text(encoding='utf-8'))


def points():
    return [p for s in SPEC['sections'] for p in s['points']]


def by_ref(ref):
    return next(p for p in points() if p['ref'] == ref)


def builder():
    spec = importlib.util.spec_from_file_location('build_fluke_6060a_gidep_spec', ROOT / 'specs' / 'build_fluke_6060a_gidep_spec.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SpecTests(unittest.TestCase):
    def test_counts_and_groups(self):
        got = {s['id']: len(s['points']) for s in SPEC['sections']}
        self.assertEqual(got, {'G-3': 1, 'G-4.1': 1, 'G-4.1b': 13, 'G-4.2a': 9, 'G-4.2b-2.5': 25, 'G-4.2b-250': 25, 'G-4.2b-520': 25, 'G-4.3': 2, 'G-4.4-0.15': 8, 'G-4.4-250': 8,
                               'G-4.4-520': 8, 'G-4.5': 9, 'G-4.6-T9': 27, 'G-4.6-T10': 27, 'G-4.7a': 6, 'G-4.7b': 18, 'G-4.8': 1, 'G-4.9': 1})
        self.assertEqual(len(points()), 214)
        self.assertEqual({p['group'] for p in points()}, {'POWERON', 'FCOREF', 'FCORF', 'RX', 'RXPWR', 'PM', 'DEVM', 'SA'})

    def test_the_100_khz_carrier_is_moved_to_150_khz_and_2_5_mhz_for_table_5(self):
        """Owner 2026-11-03: Tables 4, 6, 7 at the document's 100 kHz run at 150 kHz (the 8902A RF input); Table 5 (tuned RF level) at 2.5 MHz, where the 8902A tuned level starts."""
        moved = [p for p in points() if p.get('moved_from')]
        self.assertEqual(len(moved), 36)
        self.assertEqual({p['moved_from'] for p in moved}, {'100 kHz'})
        t5 = [p for p in moved if p['section'].startswith('G-4.2b')]
        rest = [p for p in moved if not p['section'].startswith('G-4.2b')]
        self.assertEqual((len(t5), len(rest)), (25, 11))
        self.assertTrue(all(any('100 kHz to 2.5 MHz' in f for f in p['flags']) and '2.5 MHz' in p['ref'] for p in t5))
        self.assertTrue(all(any('100 kHz to 150 kHz' in f for f in p['flags']) and '150 kHz' in p['ref'] for p in rest))
        self.assertFalse([p['ref'] for p in points() if (p.get('gen') or {}).get('freq_mhz') is not None and 0.01 < p['gen']['freq_mhz'] < 0.15])
        self.assertFalse([p['ref'] for p in points() if p.get('meas') == 'level_rx' and p['rx']['mode'] == 'tuned' and p['gen']['freq_mhz'] < 2.5])
        self.assertTrue(any('moved to 150 kHz' in d for d in SPEC['discrepancies']) and any('moved to 2.5 MHz' in d for d in SPEC['discrepancies']))
        self.assertIs(SPEC['options']['checkpoint_requires_ref'], True)

    def test_json_is_what_the_builder_makes(self):
        self.assertEqual(json.loads(json.dumps(builder().build_spec())), SPEC)

    def test_every_point_has_a_page_reference_a_limit_and_a_unique_ref(self):
        for p in points():
            self.assertTrue(p['page'].startswith('T.O. 33K3-4-911-1 para'), p['ref'])
            self.assertLessEqual(p['low'], p['high'], p['ref'])
        self.assertEqual(len({p['ref'] for p in points()}), len(points()))

    def test_frequency_tables_2_and_3(self):
        pts = [p for p in points() if p['func'] == 'FREQ']
        self.assertEqual([p['nominal'] / 1e6 for p in pts], [100.0, 111.11111, 122.22222, 133.33333, 144.44444, 155.55555, 166.66666, 177.77777, 188.88888, 199.99999, 299.99999, 399.99999, 499.99999])
        # owner 2026-11-04: above the 96270A counter's 310 MHz the points are typed from the lab's own counter
        self.assertEqual([p['meas'] for p in pts], ['fco_freq'] * 11 + ['manual'] * 2)
        self.assertTrue(all('GPS 10 MHz' in p['manual_prompt'] for p in pts[-2:]))
        for p in pts:
            self.assertAlmostEqual(p['high'] - p['nominal'], 10.0, places=3)
            self.assertAlmostEqual(p['nominal'] - p['low'], 10.0, places=3)
        ref = by_ref('4.1.5 10 MHz reference output')
        self.assertEqual((ref['low'], ref['high'], ref['meas'], ref['fco']), (9999940.0, 10000060.0, 'fco_freq', {'range': 2, 'gate_s': 2.0}))

    def test_table_4_limits(self):
        got = {(p['gen']['freq_mhz'], p['gen']['level_dbm']): (p['low'], p['high'], p['meas']) for s in SPEC['sections'] if s['id'] == 'G-4.2a' for p in s['points']}
        self.assertEqual(got[(0.15, 13)], (10.5, 15.5, 'level_rx'))
        self.assertEqual(got[(250, 10)], (7.5, 12.5, 'level_pm'))
        self.assertEqual(got[(520, 0)], (-2.5, 2.5, 'level_pm'))

    def test_table_5_is_relative_to_the_0_dbm_reference_with_2_5_db(self):
        rel = [p for p in points() if p['func'] == 'LEVEL_REL']
        self.assertEqual(len(rel), 36)
        for p in rel:
            self.assertEqual(p['meas'], 'derived')
            self.assertAlmostEqual(p['high'] - p['nominal'], 2.5)
            self.assertAlmostEqual(p['nominal'] - p['low'], 2.5)
            self.assertEqual(p['derive']['constant'], 0)
        m10 = by_ref('4.2 Table 5 250 MHz -10 dBm relative')
        self.assertEqual((m10['low'], m10['high']), (-12.5, -7.5))
        m120 = by_ref('4.2 Table 5 520 MHz -120 dBm relative')
        self.assertEqual((m120['low'], m120['high']), (-122.5, -117.5))
        self.assertEqual(m120['derive']['inputs'], ['4.2 Table 5 520 MHz 0 dBm reference', '4.2 Table 5 520 MHz -120 dBm'])
        self.assertFalse([p['ref'] for p in points() if p['func'] in ('LEVEL', 'LEVEL_REL') and p['nominal'] < -120], 'owner 2026-11-03: stop at -120 dB')

    def test_modulation_tables_6_7_8(self):
        am = {(p['gen']['freq_mhz'], p['gen']['am']['rate_hz'], p['gen']['am']['pct']): (p['low'], p['high']) for p in points() if p['func'] == 'AMDEPTH'}
        self.assertEqual(len(am), 21)
        self.assertEqual(am[(250, 1000.0, 50)], (47.0, 53.0))
        self.assertEqual(am[(520, 400.0, 90)], (84.6, 95.4))
        self.assertEqual(am[(0.15, 1000.0, 30)], (28.2, 31.8))
        thd = [p for p in points() if p['func'] == 'THD']
        self.assertEqual(len(thd), 3)
        for p in thd:
            self.assertEqual((p['high'], p.get('strict_high')), (5.0, True))
        rates = {p['nominal']: (p['low'], p['high']) for p in points() if p['func'] == 'MODRATE'}
        self.assertEqual(rates, {1000.0: (950.0, 1050.0), 400.0: (380.0, 420.0)})
        fm = {(p['gen']['freq_mhz'], p['gen']['fm']['khz']): (p['low'], p['high']) for p in points() if p['func'] == 'FMDEV'}
        self.assertEqual(fm[(0.25, 25.0)], (23750.0, 26250.0))
        self.assertEqual(fm[(520, 380.0)], (361000.0, 399000.0))
        self.assertEqual(fm[(250, 100.0)], (95000.0, 105000.0))

    def test_deviation_meter_tables_9_and_10_use_the_96270a_fm_and_the_printed_limits(self):
        dm = [p for p in points() if p['func'] == 'DEVMETER']
        self.assertEqual(len(dm), 54)
        for p in dm:
            lim = 3.0 if 'Table 9' in p['page'] else 30.0
            self.assertEqual((p['meas'], p['unit'], p['group']), ('devmeter', 'kHz', 'DEVM'))
            self.assertEqual((p['low'], p['nominal'], p['high']), (p['fmsrc']['dev_khz'] - lim, p['fmsrc']['dev_khz'], p['fmsrc']['dev_khz'] + lim))
            self.assertEqual(p['fmsrc']['level_dbm'], 7)
            self.assertNotIn('gen', p)
        self.assertEqual({p['fmsrc']['carrier_mhz'] for p in dm}, {30.0, 250.0, 500.0})
        self.assertEqual({p['fmsrc']['rate_hz'] for p in dm}, {100.0, 4000.0, 8000.0})
        self.assertEqual(sorted({p['fmsrc']['dev_khz'] for p in dm}), [10.0, 30.0, 47.0, 100.0, 300.0, 370.0])

    def test_spectral_purity_tables_11_and_12(self):
        harm = {p['gen']['freq_mhz']: p['high'] for p in points() if p['func'] == 'HARMONIC'}
        self.assertEqual(harm, {0.01: -26.0, 5: -26.0, 9.9: -26.0, 10.1: -30.0, 250: -30.0, 520: -30.0})
        spurs = [p for p in points() if p['func'] == 'SPUR']
        self.assertEqual(len(spurs), 18)
        for p in spurs:
            self.assertEqual((p['high'], p['strict_high']), (-35.0, True))
        self.assertEqual(sum(p['meas'] == 'manual' for p in spurs), 3)             # 60, 120 and 180 Hz from the carrier
        levels = [(p['gen']['level_dbm'] if 'gen' in p else None) for p in spurs]
        self.assertEqual(levels[:2], [13, 13])
        self.assertEqual(levels[-1], 1)
        self.assertEqual(by_ref('4.7 Table 12 spur 245.19000 MHz carrier 244.99 MHz +0 dBm')['sa'], {'kind': 'off', 'target_hz': 200000.0})
        self.assertEqual(by_ref('4.7 Table 12 spur 1289.98000 MHz carrier 244.99 MHz +1 dBm')['sa']['kind'], 'abs')

    def test_residuals(self):
        fm = by_ref('4.8 residual FM')
        self.assertEqual((fm['high'], fm['strict_high'], fm['gen']['freq_mhz'], fm['gen']['level_dbm']), (200.0, True, 520, 13))
        am = by_ref('4.9 residual AM')
        self.assertEqual((am['high'], am['strict_high'], am['gen']['level_dbm'], am['rx']['detector']), (0.1, True, 9, 8))

    def test_every_substituted_instrument_is_flagged(self):
        for p in points():
            if p['meas'] not in ('selftest', 'derived', 'manual'):
                self.assertTrue(any('UNVERIFIED' in f for f in p['flags']), p['ref'])

    def test_launcher_and_sidecar(self):
        side = json.loads((ROOT / 'Procedures' / 'Fluke_6060A_GIDEP_Verification.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual(side['launcher'], 'Procedures/Fluke_6060A_GIDEP_Verification.py')
        self.assertEqual(side['specs'], ['specs/fluke_6060a_gidep_pv.json'])
        import runpy
        import fluke6060a_verification as eng
        with mock.patch.object(eng, 'main') as main:
            runpy.run_path(str(ROOT / 'Procedures' / 'Fluke_6060A_GIDEP_Verification.py'), run_name='__main__')
        main.assert_called_once()
        self.assertEqual(main.call_args.kwargs['spec_path'], GIDEP_SPEC)
        self.assertEqual(main.call_args.kwargs['state_key'], '6060A-gidep')


class GidepBench(T.Bench):
    """The real App on the simulated bench with the GIDEP spec; the module settings are put back afterwards for the other 6060A tests."""

    def setUp(self):
        old = (E.SPEC_PATH, E.STATE_KEY, E.VARIANT_LABEL)
        self.addCleanup(lambda: (setattr(E, 'SPEC_PATH', old[0]), setattr(E, 'STATE_KEY', old[1]), setattr(E, 'VARIANT_LABEL', old[2]), E.configure()))
        E.SPEC_PATH, E.STATE_KEY, E.VARIANT_LABEL = GIDEP_SPEC, '6060A-gidep', 'GIDEP T.O. 33K3-4-911-1'
        super().setUp()
        self.t6.fm_max_khz = 500.0                                       # the simulated unit accepts the document's 500 kHz range
        self.t8902.tuned_floor_mhz = 2.5                                 # tuned RF level below 2.5 MHz: error 20, like the bench 8902A (2026-11-03)

        def ask(p, **k):                                               # a typed reading in the middle of the limits, in the unit the entry box shows
            _lim, _unit, scale = manual_override.entry_scale(p)
            return manual_override.parse_reading(p, str((p['low'] + p['high']) / 2 / float(scale)))
        self.app.mo_ask = ask


class GidepEngine(GidepBench):
    def test_state_is_kept_apart_from_the_instruction_manual_procedure(self):
        self.assertEqual(E.STATE_KEY, '6060A-gidep')
        self.assertEqual(len(E.POINTS), 214)
        self.assertEqual(E.SPEC['source']['limits_text'], 'GIDEP T.O. 33K3-4-911-1 (Fluke 6060A/AN)')

    def test_points_the_instruments_cannot_program_are_listed_not_tested(self):
        nt = [p for p in E.POINTS if p['not_tested']]
        self.assertEqual(len(nt), 7)
        self.assertEqual([p['ref'] for p in nt if p['func'] == 'HARMONIC'], ['4.7 Table 11 harmonics 0.01 MHz'])          # below the 0.1 MHz the driver programs
        dm = [p for p in nt if p['func'] == 'DEVMETER']
        self.assertEqual(sorted((p['fmsrc']['carrier_mhz'], p['fmsrc']['dev_khz']) for p in dm), [(30.0, 370.0)] * 3 + [(250.0, 370.0)] * 3)      # 96270A Table 3-26: 300 kHz at 30 and 250 MHz
        self.assertTrue(all(p['unavailable'].startswith('not tested') for p in nt))

    def test_fm_above_99_9_khz_is_allowed_by_the_spec_option_and_stays_flagged(self):
        self.assertEqual(E.SPEC['options']['fm_max_khz'], 500.0)
        big = [p for p in E.POINTS if p['func'] == 'FMDEV' and p['gen']['fm']['khz'] > 99.9]
        self.assertEqual(sorted(p['gen']['fm']['khz'] for p in big), [100.0, 100.0, 250.0, 250.0, 380.0, 380.0])
        for p in big:
            self.assertFalse(p['not_tested'])
            self.assertTrue(any('UNVERIFIED' in f and '99.9 kHz' in f for f in p['flags']))

    def test_the_instruction_manual_procedure_still_stops_at_99_9_khz(self):
        from drivers.fluke_6060a import Fluke6060A
        from drivers.base import InstrumentError
        with self.assertRaises(InstrumentError):
            Fluke6060A.fm(mock.Mock(low_rate_fm=False), 100.0)

    def test_every_point_passes_on_the_simulated_bench_and_rf_is_off_after_each(self):
        self.run_points('', seconds=3000)
        self.assertEqual(self.errors(), [])
        self.assertEqual(len(self.app.found), 207)
        self.assertEqual(self.non_pass(), [])
        self.assertTrue(self.rf_at_record and all(not rf for _ref, rf, _lf in self.rf_at_record if not _ref.startswith(('4.1.5', '4.6', '4.7 Table 12 spur 244.99006', '4.7 Table 12 spur 244.99012', '4.7 Table 12 spur 244.99018'))))

    def test_150_khz_carrier_is_keyed_in(self):
        """Owner 2026-11-03: the document's 100 kHz carrier is moved to 150 kHz, where the 8902A RF input starts, so it is tuned by keying the carrier in (0.1MZ gave error 10 / 20)."""
        low = next(p for p in points() if p['meas'] == 'am_depth' and p['gen']['freq_mhz'] < 1)
        self.assertEqual(low['gen']['freq_mhz'], 0.15)
        self.run_points(refs=[low['ref']])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])
        sent = [c for c in self.t8902.sent if c]
        self.assertTrue(any(c.endswith('MZ') and not c.startswith('37') for c in sent), sent)

    def test_the_simulated_8902a_refuses_a_keyed_in_100_khz_tuning_with_error_10(self):
        from drivers.hp_8902a import HP8902A, decode_reading
        self.connect()
        rx = self.app.io.rx
        with mock.patch.object(HP8902A, 'MIN_MANUAL_TUNE_MHZ', 0.0):                     # the old behaviour: key the 100 kHz in
            with self.assertRaises(Exception) as cm:
                rx.measure_am_percent(0.1, detector=9, hp=2, lp=1)
        self.assertIn('error 10', str(cm.exception))

    def test_manual_tuning_is_kept_at_and_above_150_khz(self):
        from drivers.hp_8902a import HP8902A
        self.assertEqual(HP8902A._tune(HP8902A, 0.15), ('tune.mhz', {'mhz': 0.15}))
        self.assertEqual(HP8902A._tune(HP8902A, 0.1), ('tune.auto', {}))
        self.assertEqual(HP8902A._tune(HP8902A, 520.0), ('tune.mhz', {'mhz': 520.0}))

    def test_typed_points_are_marked_manual_and_judged(self):
        self.run_points(refs=['4.1 Table 3 399.99999 MHz', '4.6 Table 9 30 MHz 100 Hz 10 kHz'])
        found = {E.POINTS[int(k) - 1]['ref']: r for k, r in self.app.found.items()}
        self.assertEqual(len(found), 2)
        self.assertTrue(all(r['manual'] and r['result'] == 'PASS' for r in found.values()))
        self.assertFalse(rf_state(self.bench)['rf_on'])                                    # the 6060A RF stayed off
        self.assertEqual(self.pm.state['OUTP'], '0')                                       # the 96270A output is off again after the deviation-meter point
        self.assertEqual(self.pm.state['INST'], 'SINE')
        self.assertIn('FM:DEV 10000', self.pm.sent)
        self.assertEqual(rf_state(self.bench)['frequency_hz'], 30000000)                    # the 6060A carrier frequency was set to the 96270A carrier (30 MHz), read back
        self.assertIn('FM:INT:FREQ 100', self.pm.sent)
        self.app.mo_ask = lambda p, **k: manual_override.parse_reading(p, '400.001')      # 400.001 MHz: outside +/-10 Hz
        self.app.found.clear(); self.app.results.clear()
        self.run_points(refs=['4.1 Table 3 399.99999 MHz'])
        self.assertEqual([r['result'] for r in self.app.found.values()], ['FAIL'])

    def test_relative_level_rows_are_computed_from_the_reference(self):
        self.run_points(refs=['4.2 Table 5 250 MHz 0 dBm reference', '4.2 Table 5 250 MHz -10 dBm', '4.2 Table 5 250 MHz -10 dBm relative'])
        rel = next(r for k, r in self.app.found.items() if E.POINTS[int(k) - 1]['func'] == 'LEVEL_REL')
        self.assertEqual(rel['result'], 'PASS')
        self.assertTrue(-12.5 <= rel['reading'] <= -7.5)


class GidepDemo(GidepBench):
    DEMO = True

    def test_demo_readings_are_all_synthetic(self):
        self.app.execute([p for p in self.app.active_points()])
        self.assertTrue(self.h.pump(300))
        self.assertTrue(self.app.found)
        self.assertTrue(all(r.get('synthetic') for r in self.app.found.values()))


if __name__ == '__main__':
    unittest.main()


class UpfrontCalibrations(unittest.TestCase):
    """The three 8902A calibrations are asked once, before the first point, not at the first section that needs each one."""

    def _pts(self):
        E.load_spec(GIDEP_SPEC)
        return E.POINTS

    def setUp(self):
        self.answer = False
        p = mock.patch.object(E.port, 'ask_yes_no', side_effect=lambda title, text, **k: (self.asked.append((title, text, k)), self.answer)[1])
        p.start(); self.addCleanup(p.stop)
        self.asked = []

    def _app(self, demo=False):
        app = E.App.__new__(E.App)
        app.demo, app._prep_done, app.calls, app.root = demo, set(), [], None
        app.status = mock.MagicMock()
        app.io = mock.MagicMock()
        app.connected_io = lambda: app.io
        app._run_preps = lambda points, i, p, key, preps: app.calls.append(('preps', i, p['id'], list(preps)))
        app._next = lambda points, i, previous, after_prep=False: app.calls.append(('next', i))
        return app

    def test_all_needed_calibrations_come_first_in_one_pass(self):
        pts = self._pts()
        app = self._app()
        app._upfront_preps(pts)
        self.assertEqual(len(app.calls), 1)
        kind, i, pid, preps = app.calls[0]
        self.assertEqual((kind, i), ('preps', 0))
        self.assertEqual(sorted(preps), ['rx_am', 'rx_fm', 'rx_power'])

    def test_skipped_points_need_no_calibration_and_none_means_straight_to_the_first_point(self):
        pts = [dict(p, skip=True) for p in self._pts()]
        app = self._app()
        app._upfront_preps(pts)
        self.assertEqual(app.calls, [('next', 0)])

    def test_demo_asks_for_nothing(self):
        app = self._app(demo=True)
        app._upfront_preps(self._pts())
        self.assertEqual(app.calls, [('next', 0)])

    def test_already_calibrated_skips_all_three_and_logs_it(self):
        """Owner 2026-11-03: 'give me a skip / already cal'd button'. One question; Yes skips every needed calibration, each skip is written to the command log."""
        self.answer = True
        app = self._app()
        app._upfront_preps(self._pts())
        self.assertEqual(app.calls, [('next', 0)])
        self.assertEqual(app._prep_done, {'rx_power', 'rx_am', 'rx_fm'})
        self.assertEqual(len(self.asked), 1)
        title, text, k = self.asked[0]
        self.assertEqual((title, k.get('default')), ('8902A calibration', 'no'))
        for words in ('RF power sensor', 'AM calibration', 'FM calibration'):
            self.assertIn(words, text)
        logged = [c.args[1] for c in app.io.log.add.call_args_list]
        self.assertEqual(len(logged), 3)
        self.assertTrue(all('skipped, already calibrated' in t for t in logged))

    def test_no_calibrates_and_a_second_run_on_the_same_connection_asks_nothing(self):
        app = self._app()
        app._upfront_preps(self._pts())
        self.assertEqual(app.calls[0][0], 'preps')
        app._prep_done |= {'rx_power', 'rx_am', 'rx_fm'}           # the calibrations ran (_preps_done)
        app.calls.clear(); self.asked.clear()
        app._upfront_preps(self._pts())                              # the next Run / Run section
        self.assertEqual((app.calls, self.asked), ([('next', 0)], []))

    def test_execute_keeps_the_calibrations_and_disconnect_forgets_them(self):
        src = Path(E.__file__).read_text(encoding='utf-8')
        body = src[src.index('    def execute(self, points):'):src.index('    def reset_run(self):')]
        self.assertNotIn('self._prep_done = set()', body)
        disc = src[src.index('    def disconnect(self):'):src.index('    def connected_io(self)')]
        self.assertIn('self._prep_done = set()', disc)


class StaleCheckpoint(unittest.TestCase):
    """Results are keyed by point number: a checkpoint saved before the 100 kHz -> 150 kHz move must not put its 100 kHz readings on the 150 kHz points."""

    def pts(self):
        return [dict(id=1, ref='4.2 Table 4 250 MHz +13 dBm'), dict(id=2, ref='4.2 Table 4 150 kHz +13 dBm', moved_from='100 kHz')]

    def test_old_results_without_a_ref_are_dropped_only_on_moved_points(self):
        data = dict(results={'1': dict(reading=13.1), '2': dict(reading=13.0)}, left_results={'2': dict(reading=13.0)})
        self.assertEqual(E.drop_stale_results(data, self.pts()), 2)
        self.assertEqual(list(data['results']), ['1'])
        self.assertEqual(data['left_results'], {})

    def test_a_result_naming_another_point_is_dropped_and_a_matching_one_kept(self):
        data = dict(results={'1': dict(reading=13.1, ref='4.2 Table 4 100 kHz +13 dBm'), '2': dict(reading=13.0, ref='4.2 Table 4 150 kHz +13 dBm'), '9': dict(reading=1)})
        self.assertEqual(E.drop_stale_results(data, self.pts()), 2)
        self.assertEqual(list(data['results']), ['2'])


class CalibrateOncePerConnection(GidepBench):
    """Owner 2026-11-03: 'remove the need to calibrate the 8902 sensor in each section or give me a skip / already cal'd button'. On the simulated bench: a second Run on the same
    connection asks for no calibration; on a fresh connection 'already calibrated' (Yes) skips them, and the command log says so."""

    def power_refs(self):
        return [p['ref'] for p in E.POINTS if p['meas'] == 'level_rx' and p['rx']['mode'] == 'power'][:1]

    def cal_prompts(self):
        return [t for t in self.titles if t.startswith('Calibrate the 8902A')]

    def setUp(self):
        super().setUp()
        self.titles = []
        inner = self.h.on_confirm

        def operator(title, heading, steps, facts):
            self.titles.append(title)
            return inner(title, heading, steps, facts)
        self.h.on_confirm = operator

    def test_second_run_on_the_same_connection_does_not_calibrate_again(self):
        self.run_points(refs=self.power_refs())
        self.assertEqual(self.cal_prompts(), ['Calibrate the 8902A RF power'])
        self.titles.clear()
        self.run_points(refs=self.power_refs())
        self.assertEqual(self.cal_prompts(), [])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])

    def test_already_calibrated_skips_and_is_in_the_command_log(self):
        self.already_calibrated = True
        self.run_points(refs=self.power_refs())
        self.assertEqual(self.cal_prompts(), [])
        self.assertEqual(self.errors(), [])
        self.assertTrue(any('RF power sensor (zero and 1 mW calibration) skipped, already calibrated' in line for line in self.app.io.log.lines()))
        self.assertFalse(any('C1T3SC' in c for c in self.t8902.sent if c), 'no calibration command is sent when it is skipped')

    def test_disconnect_forgets_the_calibrations(self):
        self.run_points(refs=self.power_refs())
        self.app.disconnect()
        self.titles.clear()
        self.run_points(refs=self.power_refs())
        self.assertEqual(self.cal_prompts(), ['Calibrate the 8902A RF power'])


class TunedLevelFloor(GidepBench):
    """Owner bench 2026-11-03: the 8902A tuned RF level at 150 kHz showed error 20 (value out of range); its range is 2.5 MHz to 1300 MHz (p. 1-22). The simulator now does the same,
    and the Table 5 low carrier is 2.5 MHz."""

    def test_the_simulated_8902a_refuses_a_tuned_level_at_150_khz_with_error_20(self):
        self.connect()
        with self.assertRaises(Exception) as cm:
            self.app.io.rx.tuned_rf_level_dbm(0.15)
        self.assertIn('error 20', str(cm.exception))

    def test_table_5_low_carrier_is_2_5_mhz_and_runs_clean(self):
        low = [p for p in E.POINTS if p['section'] == 'G-4.2b-2.5']
        self.assertEqual(len(low), 25)
        self.assertTrue(all(p['gen']['freq_mhz'] == 2.5 for p in low if p.get('gen')))
        self.run_points(refs=[p['ref'] for p in low if p['meas'] != 'derived'])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])


class DeviationMeterNoRfCheck(GidepBench):
    """Owner 2026-11-03: 'the deviation meter errors out while trying to read if the output of the 6060 is off ... the output will never be on in the deviation meter mode'.
    From the first deviation-meter point until the next point that uses the 6060A output, the RF-off read-back (RO0 + LM99) is not made, and the command log says so."""

    def test_no_rf_off_read_back_during_deviation_meter_points_and_back_after(self):
        dm = [p for p in E.POINTS if p['meas'] == 'devmeter' and not p.get('not_tested')][:2]
        after = next(p for p in E.POINTS[E.POINTS.index(dm[-1]) + 1:] if p['meas'] in ('harmonic', 'spur') and not p.get('not_tested'))
        self.connect()
        n = len(self.t6.sent)
        self.run_points(refs=[p['ref'] for p in dm])
        self.assertEqual(self.errors(), [])
        self.assertEqual(len([k for k in self.app.found if E.POINTS[int(k) - 1]['meas'] == 'devmeter']), 2)
        sent = self.t6.sent[n:]
        first_fr = next(i for i, c in enumerate(sent) if c.startswith('FR'))
        self.assertIn('RO0', sent[:first_fr], 'RF OFF is confirmed before the deviation-meter points (reset / wiring prompt)')
        self.assertNotIn('RO0', sent[first_fr:], 'no RF-off read-back once the 6060A is on the deviation-meter carrier')
        self.assertNotIn('RO1', sent[first_fr:])
        self.assertTrue([l for l in self.app.io.log.lines() if 'RF OFF read-back skipped: deviation-meter mode' in l])
        m = len(self.t6.sent)
        self.run_points(refs=[after['ref']])
        self.assertEqual(self.errors(), [])
        back = self.t6.sent[m:]
        self.assertIn('RO1', back)
        self.assertIn('RO0', back[back.index('RO1'):], 'the next point switches RF on and confirms it off again')


class SpurCarrierApproach(GidepBench):
    """Owner bench 2026-11-03: 'we keep getting an uncal message on the 6060 unless we start at 242MHz and increment up to the 244MHz. If we try to go directly to 244MHz we get
    the uncal message'. The Table 12 carriers 244 and 244.99 MHz are reached from 242 MHz in 1 MHz steps (spec gen.approach_mhz); the simulator models the UNCAL (opt-in band)."""

    def setUp(self):
        super().setUp()
        self.t6.approach_band = (242.0, 245.0)

    def spurs(self, mhz):
        return [p for p in E.POINTS if p['func'] == 'SPUR' and p['meas'] == 'spur' and p['gen']['freq_mhz'] == mhz]

    def test_the_spec_carries_the_approach_only_where_needed(self):
        self.assertEqual({tuple(p['gen']['approach_mhz']) for p in self.spurs(244.0)}, {(242.0, 243.0)})
        self.assertEqual({tuple(p['gen']['approach_mhz']) for p in self.spurs(244.99)}, {(242.0, 243.0, 244.0)})
        self.assertTrue(all('approach_mhz' not in p['gen'] for p in self.spurs(185.0)))
        typed = [p for p in E.POINTS if p['func'] == 'SPUR' and p['meas'] == 'manual']
        self.assertTrue(typed and all('from 242 MHz upward' in p['manual_prompt'] for p in typed))

    def test_244_mhz_carriers_run_without_uncal(self):
        refs = [p['ref'] for p in self.spurs(244.0) + self.spurs(244.99)]
        n = len(self.t6.sent)
        self.run_points(refs=refs)
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])
        sent = self.t6.sent[n:]
        i242, i243 = sent.index('FR242.00000MZ'), sent.index('FR243.00000MZ')
        self.assertLess(i242, i243)
        self.assertLess(i243, sent.index('FR244.00000MZ'))

    def test_set_directly_the_simulated_6060a_reports_uncal(self):
        p = self.spurs(244.99)[0]
        p['gen'].pop('approach_mhz')
        self.run_points(refs=[p['ref']])
        self.assertTrue(any('UNCAL' in (d[3] or '') or 'PLL' in (d[3] or '') for d in self.errors()), self.h.dialogs[-3:])


class AmFilterAt400Hz(GidepBench):
    """Owner bench 2026-11-03: 'the 8902 should have a high pass filter of 50Hz, not 300Hz' on the 400 Hz-rate AM points (Table 7): the 300 Hz high-pass cut the tone
    (30 % read 26.63 %, 70 % read 61.8 %). Every 400 Hz-rate AM depth point uses H1 (50 Hz); the 1 kHz ones keep H2 (300 Hz)."""

    def test_spec_filters_follow_the_rate(self):
        am = [p for p in E.POINTS if p['func'] == 'AMDEPTH']
        self.assertEqual({(p['gen']['am']['rate_hz'], p['rx']['hp']) for p in am}, {(400.0, 1), (1000.0, 2)})
        self.assertEqual(len([p for p in am if p['rx']['hp'] == 1]), 9)

    def test_a_400_hz_point_sends_h1(self):
        p = next(p for p in E.POINTS if p['func'] == 'AMDEPTH' and p['gen']['am']['rate_hz'] == 400.0 and p['gen']['freq_mhz'] == 250)
        n = len(self.t8902.sent)
        self.run_points(refs=[p['ref']])
        self.assertEqual(self.errors(), [])
        sent = self.t8902.sent[n:]
        self.assertIn('H1', sent)
        self.assertNotIn('H2', sent[sent.index('H1'):])


class PllLockWait(GidepBench):
    """Owner bench 2026-11-03: 'output is UNCAL (0.0 dBm): 000000,000010,000400: main or reference PLL unlocked' at 244.99 MHz although the carrier is approached from 242 MHz.
    When the PLL unlock is the only UNCAL reason the driver reads IU again (up to 5 x 0.4 s) and goes on once it locks; a lasting unlock still stops the run."""

    def setUp(self):
        super().setUp()
        self.t6.approach_band = (242.0, 245.0)
        self.slept = []
        real = E.drivers.fluke_6060a.time.sleep
        p = mock.patch.object(E.drivers.fluke_6060a.time, 'sleep', side_effect=lambda s: self.slept.append(s))
        p.start(); self.addCleanup(p.stop)

    def point(self):
        return next(p for p in E.POINTS if p['func'] == 'SPUR' and p['meas'] == 'spur' and p['gen']['freq_mhz'] == 244.99 and p['gen']['level_dbm'] == 0)

    def test_a_loop_that_locks_within_the_wait_goes_on(self):
        self.t6.pll_settle_reads = 2
        self.run_points(refs=[self.point()['ref']])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])
        self.assertTrue([l for l in self.app.io.log.lines() if 'PLL unlocked' in l and 'waiting 0.4 s for lock' in l])

    def test_a_lasting_unlock_still_stops_the_run(self):
        p = self.point()
        p['gen'].pop('approach_mhz')                                     # set directly: the simulated PLL stays unlocked
        self.run_points(refs=[p['ref']])
        self.assertTrue(any('PLL unlocked' in (d[3] or '') for d in self.errors()), self.h.dialogs[-3:])
        self.assertEqual(len([l for l in self.app.io.log.lines() if 'waiting 0.4 s for lock' in l]), E.drivers.Fluke6060A.PLL_LOCK_TRIES)

    def test_another_uncal_reason_does_not_wait(self):
        from drivers.fluke_6060a import Fluke6060A
        self.assertFalse(Fluke6060A._pll_only((0, 0o010, 0o001)))
        self.assertFalse(Fluke6060A._pll_only((0o002, 0o010, 0)))
        self.assertTrue(Fluke6060A._pll_only((0, 0o010, 0)))


class Counter96270A(GidepBench):
    """Owner 2026-11-04: "can we abandon it and use the frequency counter built into the 96270?" The 10 MHz reference output (range 2) and Tables 2 / 3 to 299.99999 MHz (range 3, 6060A at
    +7 dBm) are read on the 96270A counter (rear 300 MHz Counter BNC, Remote Programmers Manual pp. 32, 41 to 43, 49); the 96270A must be on its external (GPS) reference."""

    def test_the_reference_and_the_rf_points_are_read_on_the_96270a_counter(self):
        refs = ['4.1.5 10 MHz reference output', '4.1 Table 2 100.00000 MHz', '4.1 Table 3 299.99999 MHz']
        self.run_points(refs=refs)
        self.assertEqual(self.errors(), [])
        found = {E.POINTS[int(k) - 1]['ref']: r for k, r in self.app.found.items()}
        self.assertEqual(sorted(found), sorted(refs))
        self.assertTrue(all(r['result'] == 'PASS' and not r['manual'] for r in found.values()))
        sent = self.pm.sent
        self.assertIn('INST FCO', sent)
        self.assertIn(':FCO:RANG 2', sent)
        self.assertIn(':FCO:RANG 3', sent)
        self.assertIn(':TRIG:GATE 2', sent)
        self.assertEqual(self.pm.state['INST'], 'SINE')                 # back to the leveled sine after each reading
        self.assertEqual(self.pm.state['OUTP'], '0')
        self.assertFalse(rf_state(self.bench)['rf_on'])

    def test_a_10_mhz_reading_outside_6_ppm_fails(self):
        self.pm.ref_out_hz = 10e6 * (1 + 8e-6)
        self.run_points(refs=['4.1.5 10 MHz reference output'])
        self.assertEqual([r['result'] for r in self.app.found.values()], ['FAIL'])

    def test_the_96270a_on_its_internal_reference_stops_with_a_clear_message(self):
        self.pm.rosc = 'INT'
        self.app.mo_failed = lambda p, exc: None                          # no typed replacement: the run stops on the error
        self.run_points(refs=['4.1 Table 2 100.00000 MHz'])
        self.assertTrue(any('not EXTernal' in (d[3] or '') for d in self.errors()), self.h.dialogs[-3:])
        self.assertFalse(rf_state(self.bench)['rf_on'], 'RF is off after the failed point')
        self.assertEqual(self.pm.state['INST'], 'SINE')

    def test_a_power_level_point_after_the_counter_selects_the_power_meter_again(self):
        lvl = next(p for p in E.POINTS if p['meas'] == 'level_pm')
        self.run_points(refs=['4.1 Table 2 100.00000 MHz', lvl['ref']])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.non_pass(), [])
        i = max(i for i, c in enumerate(self.pm.sent) if c == 'INST FCO')
        self.assertTrue(any(c.startswith('INST PMET') for c in self.pm.sent[i:]))
