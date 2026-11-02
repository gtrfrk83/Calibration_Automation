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
        self.assertEqual(got, {'G-3': 1, 'G-4.1': 1, 'G-4.1b': 13, 'G-4.2a': 9, 'G-4.2b-0.1': 27, 'G-4.2b-250': 27, 'G-4.2b-520': 27, 'G-4.3': 2, 'G-4.4-0.1': 8, 'G-4.4-250': 8,
                               'G-4.4-520': 8, 'G-4.5': 9, 'G-4.6-T9': 27, 'G-4.6-T10': 27, 'G-4.7a': 6, 'G-4.7b': 18, 'G-4.8': 1, 'G-4.9': 1})
        self.assertEqual(len(points()), 220)
        self.assertEqual({p['group'] for p in points()}, {'POWERON', 'REFOSC', 'RX', 'RXPWR', 'PM', 'DEVM', 'SA'})

    def test_json_is_what_the_builder_makes(self):
        self.assertEqual(json.loads(json.dumps(builder().build_spec())), SPEC)

    def test_every_point_has_a_page_reference_a_limit_and_a_unique_ref(self):
        for p in points():
            self.assertTrue(p['page'].startswith('T.O. 33K3-4-911-1 para'), p['ref'])
            self.assertLessEqual(p['low'], p['high'], p['ref'])
        self.assertEqual(len({p['ref'] for p in points()}), len(points()))

    def test_frequency_tables_2_and_3(self):
        pts = [p for p in points() if p['func'] == 'FREQ']
        self.assertEqual([p['gen']['freq_mhz'] for p in pts], [100.0, 111.11111, 122.22222, 133.33333, 144.44444, 155.55555, 166.66666, 177.77777, 188.88888, 199.99999, 299.99999, 399.99999, 499.99999])
        for p in pts:
            self.assertAlmostEqual(p['high'] - p['nominal'], 10.0, places=3)
            self.assertAlmostEqual(p['nominal'] - p['low'], 10.0, places=3)
        ref = by_ref('4.1.5 10 MHz reference output')
        self.assertEqual((ref['low'], ref['high'], ref['meas']), (9999940.0, 10000060.0, 'manual'))

    def test_table_4_limits(self):
        got = {(p['gen']['freq_mhz'], p['gen']['level_dbm']): (p['low'], p['high'], p['meas']) for s in SPEC['sections'] if s['id'] == 'G-4.2a' for p in s['points']}
        self.assertEqual(got[(0.1, 13)], (10.5, 15.5, 'level_rx'))
        self.assertEqual(got[(250, 10)], (7.5, 12.5, 'level_pm'))
        self.assertEqual(got[(520, 0)], (-2.5, 2.5, 'level_pm'))

    def test_table_5_is_relative_to_the_0_dbm_reference_with_2_5_db(self):
        rel = [p for p in points() if p['func'] == 'LEVEL_REL']
        self.assertEqual(len(rel), 39)
        for p in rel:
            self.assertEqual(p['meas'], 'derived')
            self.assertAlmostEqual(p['high'] - p['nominal'], 2.5)
            self.assertAlmostEqual(p['nominal'] - p['low'], 2.5)
            self.assertEqual(p['derive']['constant'], 0)
        m10 = by_ref('4.2 Table 5 250 MHz -10 dBm relative')
        self.assertEqual((m10['low'], m10['high']), (-12.5, -7.5))
        m127 = by_ref('4.2 Table 5 520 MHz -127 dBm relative')
        self.assertEqual((m127['low'], m127['high']), (-129.5, -124.5))
        self.assertEqual(m127['derive']['inputs'], ['4.2 Table 5 520 MHz 0 dBm reference', '4.2 Table 5 520 MHz -127 dBm'])

    def test_modulation_tables_6_7_8(self):
        am = {(p['gen']['freq_mhz'], p['gen']['am']['rate_hz'], p['gen']['am']['pct']): (p['low'], p['high']) for p in points() if p['func'] == 'AMDEPTH'}
        self.assertEqual(len(am), 21)
        self.assertEqual(am[(250, 1000.0, 50)], (47.0, 53.0))
        self.assertEqual(am[(520, 400.0, 90)], (84.6, 95.4))
        self.assertEqual(am[(0.1, 1000.0, 30)], (28.2, 31.8))
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

    def test_deviation_meter_tables_9_and_10_are_typed_with_the_printed_limits(self):
        dm = [p for p in points() if p['func'] == 'DEVMETER']
        self.assertEqual(len(dm), 54)
        self.assertEqual({(p['low'], p['high']) for p in dm if 'Table 9' in p['page']}, {(-3.0, 3.0)})
        self.assertEqual({(p['low'], p['high']) for p in dm if 'Table 10' in p['page']}, {(-30.0, 30.0)})
        self.assertTrue(all(p['meas'] == 'manual' and 'gen' not in p for p in dm))

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

        def ask(p, **k):                                               # a typed reading in the middle of the limits, in the unit the entry box shows
            _lim, _unit, scale = manual_override.entry_scale(p)
            return manual_override.parse_reading(p, str((p['low'] + p['high']) / 2 / float(scale)))
        self.app.mo_ask = ask


class GidepEngine(GidepBench):
    def test_state_is_kept_apart_from_the_instruction_manual_procedure(self):
        self.assertEqual(E.STATE_KEY, '6060A-gidep')
        self.assertEqual(len(E.POINTS), 220)
        self.assertEqual(E.SPEC['source']['limits_text'], 'GIDEP T.O. 33K3-4-911-1 (Fluke 6060A/AN)')

    def test_points_the_driver_cannot_program_are_listed_not_tested(self):
        nt = [p for p in E.POINTS if p['not_tested']]
        self.assertEqual(len(nt), 7)
        self.assertEqual(sorted(p['ref'] for p in nt if p['func'] == 'HARMONIC'), ['4.7 Table 11 harmonics 0.01 MHz'])
        self.assertEqual(sorted(p['gen']['fm']['khz'] for p in nt if p['func'] == 'FMDEV'), [100.0, 100.0, 250.0, 250.0, 380.0, 380.0])
        self.assertTrue(all(p['unavailable'].startswith('not tested') for p in nt))

    def test_every_point_passes_on_the_simulated_bench_and_rf_is_off_after_each(self):
        self.run_points('', seconds=3000)
        self.assertEqual(self.errors(), [])
        self.assertEqual(len(self.app.found), 213)
        self.assertEqual(self.non_pass(), [])
        self.assertTrue(self.rf_at_record and all(not rf for _ref, rf, _lf in self.rf_at_record if not _ref.startswith(('4.1.5', '4.6', '4.7 Table 12 spur 244.99006', '4.7 Table 12 spur 244.99012', '4.7 Table 12 spur 244.99018'))))

    def test_typed_points_are_marked_manual_and_judged(self):
        self.run_points(refs=['4.1.5 10 MHz reference output', '4.6 Table 9 30 MHz 100 Hz 10 kHz'])
        found = {E.POINTS[int(k) - 1]['ref']: r for k, r in self.app.found.items()}
        self.assertEqual(len(found), 2)
        self.assertTrue(all(r['manual'] and r['result'] == 'PASS' for r in found.values()))
        self.app.mo_ask = lambda p, **k: manual_override.parse_reading(p, '10.001')       # 10.001 MHz: outside +/-6 ppm
        self.app.found.clear(); self.app.results.clear()
        self.run_points(refs=['4.1.5 10 MHz reference output'])
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
