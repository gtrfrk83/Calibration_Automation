"""Datasheet Builder: matching points to the imported standards (5520A, 5522A, 5560A, 5790B, 96270A, 8563E, 8902A + driver-only 53131A / 53132A), coverage
reasons, TAR / TUR, CMC clamp, ranking, overrides, and the driver table.   Run:  python -m unittest tests.test_datasheet_builder_match"""
import os
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import specmanager as sm  # noqa: E402
import uncertainty  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

DB = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')


class M(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sm.seed(path=DB)
        cls.m = dm.Matcher(DB)
        cls.scope = uncertainty.load()

    def match(self, ds, **kw):
        before = ds.to_dict()
        res = self.m.match(ds, **kw)
        self.assertEqual(ds.to_dict(), before, 'matching must not change the datasheet')
        return res


class Dmm(M):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ds = fx.dmm_34461a_like()
        cls.res = cls.m.match(cls.ds)

    def test_every_standard_is_considered(self):
        self.assertEqual(self.res.standards, ['5520A', '5522A', '5560A', '5790B', '8563E', '8902A', '96270A', '53131A', '53132A'])

    def test_dc_volts_all_covered_and_automatable(self):
        s = self.res.summary()['dcv']
        self.assertEqual((s['points'], s['assigned'], s['uncovered'], s['automatable']), (35, 35, 0, 35))
        a = self.res.assignments['dcv.r10.+5']
        self.assertIn(a.standard, ('5522A', '5560A'))
        self.assertEqual(a.automation, 'ok')
        self.assertTrue(a.can_automate)
        self.assertGreater(a.tur, 1)

    def test_candidates_ranked_best_tur_first_then_lab_default(self):
        for a in self.res.assignments.values():
            cov = [c for c in a.candidates if c.covered]
            if a.status != 'assigned':
                self.assertEqual(cov, [], a.point_id)
                continue
            self.assertEqual(a.standard, cov[0].standard)
            buckets = [dm._tur_bucket(c) for c in cov]
            self.assertEqual(buckets, sorted(buckets, reverse=True), a.point_id)
            self.assertEqual([c.rank for c in cov], list(range(1, len(cov) + 1)))
        # an exact TUR tie falls back to the lab default (5560A before 5522A for multimeters)
        tie = [dm.Candidate('5522A', True, tur=4.21), dm.Candidate('5560A', True, tur=4.24)]
        self.assertEqual([c.standard for c in dm._rank(tie, 'DCV')], ['5560A', '5522A'])
        tie = [dm.Candidate('5522A', True, tur=3.0), dm.Candidate('5560A', True, tur=5.0)]
        self.assertEqual(dm._rank(tie, 'DCV')[0].standard, '5560A')
        tie = [dm.Candidate('5522A', True, tur=None), dm.Candidate('5560A', True, tur=None)]
        self.assertEqual(dm._rank(tie, 'SCOPE_GAIN')[0].standard, '5522A')               # scope default order is 5522A first

    def test_reported_uncertainty_reuses_the_budget_and_is_never_below_the_cmc(self):
        fn = self.ds.function('dcv')
        for pid, v in (('dcv.r10.+5', 5), ('dcv.r100.+100', 100), ('dcv.r0.1.+0.1', 0.1)):
            a = self.res.assignments[pid]
            std = sm.standard(a.standard, DB)
            want = ub.build('DCV', v, 'V', standard=std, scope=self.scope)
            cand = next(c for c in a.candidates if c.standard == a.standard)
            self.assertAlmostEqual(cand.uncertainty, want.reported, 15, pid)
            self.assertGreaterEqual(cand.uncertainty, want.cmc)
            self.assertAlmostEqual(cand.accuracy, want.hit.limit, 15)
        for a in self.res.assignments.values():
            for c in a.candidates:
                if c.covered and c.cmc is not None and c.uncertainty is not None:
                    self.assertGreaterEqual(c.uncertainty, c.cmc * (1 - 1e-12), (a.point_id, c.standard))

    def test_tur_is_tolerance_over_reported_uncertainty(self):
        a = self.res.assignments['dcv.r10.+5']
        lim = self.ds.function('dcv').limit_for(self.ds.function('dcv').point('dcv.r10.+5'), '1y', self.ds)
        cand = next(c for c in a.candidates if c.standard == a.standard)
        self.assertAlmostEqual(cand.tolerance, float((lim.high - lim.low) / 2))
        self.assertAlmostEqual(cand.tur, cand.tolerance / cand.uncertainty)
        self.assertAlmostEqual(cand.tar, cand.tolerance / cand.accuracy)

    def test_period_changes_the_tolerance_and_therefore_the_tur(self):
        r90 = self.m.match(self.ds, period='90d')
        self.assertGreater(r90.assignments['dcv.r10.+5'].tolerance, 0)
        self.assertLess(r90.assignments['dcv.r10.+5'].tolerance, self.res.assignments['dcv.r10.+5'].tolerance)

    def test_ac_volts_in_the_covered_band(self):
        a = self.res.assignments['acv.r10.+10@1000']
        self.assertEqual(a.status, 'assigned')
        self.assertEqual(a.kind, 'ACV')

    def test_uncovered_frequency_too_high_names_the_limit(self):
        a = self.res.assignments['acv.r750.+750@50000']
        self.assertEqual(a.status, 'uncovered')
        self.assertEqual(a.reason, 'frequency_too_high')
        self.assertIn('10 kHz', a.message)
        self.assertIn(a, self.res.uncovered)
        self.assertEqual(self.res.summary()['acv']['uncovered'], 1)
        self.assertEqual(a.standard, '')
        self.assertFalse(a.can_automate)

    def test_ohms_current_capacitance_frequency(self):
        for pid in ('ohm2.r100.+100', 'ohm2.r1000000.+1000000', 'dci.r3.+3', 'cap.r0.000001.+0.000001'):
            self.assertEqual(self.res.assignments[pid].status, 'assigned', pid)
        cap = self.res.assignments['cap.r0.000001.+0.000001']
        self.assertEqual(cap.automation, 'unverified')                      # capacitance output is not verified on hardware
        self.assertTrue(cap.can_automate)
        f = self.res.assignments['freq.r300000.+1000~1']
        self.assertEqual((f.status, f.automation), ('assigned', 'ok'))

    def test_out_of_range_and_unknown_function(self):
        ds = fx.dmm_34461a_like()
        fn = ds.function('dcv')
        fn.add_range('5000', '0.01')
        ds.set_spec(fn, '0.1 % of reading', range_id='r5000')
        db.add_point(fn, 5000)
        t = ds.add_function('TEMP', settings={'tc_type': 'Q'})
        t.add_range('1000', '0.1')
        ds.set_spec(t, '1 degC' if False else '1 °C')
        db.add_point(t, 100)
        res = self.m.match(ds)
        big = res.assignments['dcv.r5000.+5000']
        self.assertEqual((big.status, big.reason), ('uncovered', 'out_of_range'))
        self.assertIn('1.02 k', big.message.replace(' ', ' ') if False else big.message)
        q = res.assignments['temp.r1000.+100']
        self.assertEqual((q.status, q.reason), ('uncovered', 'no_standard_for_function'))

    def test_temperature_uses_the_thermocouple_type_and_degc_rows_only(self):
        ds = db.Datasheet('A', 'T1', 'T')
        ds.set_periods([('1y', 'y')], '1y')
        t = ds.add_function('TEMP', settings={'tc_type': 'K'})
        t.add_range('2000', '0.1')
        ds.set_spec(t, '1 °C')
        db.add_point(t, 100)
        db.add_point(t, 1300)
        res = self.m.match(ds)
        a = res.assignments['temp.r2000.+100']
        self.assertEqual(a.status, 'assigned')
        self.assertEqual(a.automation, 'unverified')
        self.assertIsNotNone(a.tur)                                            # degC tolerance against a degC accuracy
        cand = next(c for c in a.candidates if c.standard == a.standard)
        self.assertIn('Type K', cand.row)
        self.assertIsNone(cand.cmc)                                            # temperature is not in the A2LA scope: no clamp
        self.assertTrue(any('A2LA' in n for n in cand.notes))
        hot = res.assignments['temp.r2000.+1300']
        self.assertEqual(hot.status, 'assigned')                               # 1372 degC is the K limit

    def test_overrides(self):
        pid = 'dcv.r10.+5'
        auto = self.res.assignments[pid].standard
        other = '5522A' if auto == '5560A' else '5560A'
        r = self.m.match(self.ds, overrides={pid: other})
        a = r.assignments[pid]
        self.assertEqual((a.status, a.standard, a.mode, a.overridden), ('assigned', other, 'override', True))
        # an override that cannot cover the point stays visible as uncovered
        r = self.m.match(self.ds, overrides={pid: '5790B'})
        self.assertEqual((r.assignments[pid].status, r.assignments[pid].overridden), ('uncovered', True))
        self.assertIn(r.assignments[pid], r.uncovered)
        r = self.m.match(self.ds, overrides={pid: 'MANUAL'})
        self.assertEqual((r.assignments[pid].status, r.assignments[pid].mode), ('manual', 'manual'))
        r = self.m.match(self.ds, overrides={pid: 'ZZZ'})
        self.assertEqual((r.assignments[pid].status, r.assignments[pid].reason), ('uncovered', 'unknown_standard'))
        # the datasheet's own stored assignments are used too
        ds = fx.dmm_34461a_like()
        ds.assignments[pid] = other
        self.assertEqual(self.m.match(ds).assignments[pid].standard, other)

    def test_disabled_points_are_skipped_and_results_serialise(self):
        ds = fx.dmm_34461a_like()
        ds.function('dcv').points[0].enabled = False
        res = self.m.match(ds)
        self.assertNotIn(ds.function('dcv').points[0].id, res.assignments)
        import json
        d = json.loads(json.dumps(res.to_dict()))
        self.assertEqual(d['period'], '1y')
        self.assertIn('dcv', d['summary'])
        json.dumps(res.assignments['dcv.r10.+5'].to_dict(candidates=True))

    def test_ac_without_a_frequency_is_reported_not_raised(self):
        ds = fx.acv_bands_sheet()
        ds.function('acv').points[0].frequency = None
        res = self.m.match(ds)
        a = res.assignments[ds.function('acv').points[0].id]
        self.assertEqual(a.status, 'uncovered')


class AcBands(M):
    def test_band_sheet_is_covered_and_high_frequency_is_not(self):
        ds = fx.acv_bands_sheet()
        res = self.match(ds)
        self.assertEqual(res.summary()['acv']['uncovered'], 0)
        fn = ds.function('acv')
        ds.set_spec(fn, '1 % of reading', f_lo='20000', f_hi='5000000')
        db.add_point(fn, 1, 'r1', 2000000)
        res = self.match(ds)
        a = res.assignments['acv.r1.+1@2000000']
        self.assertEqual((a.status, a.reason), ('uncovered', 'frequency_too_high'))
        self.assertIn('500 kHz', a.message)


class Generator(M):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ds = fx.generator_33220a_like()
        cls.res = cls.m.match(cls.ds)

    def test_ac_amplitude_is_measured_by_the_5790b(self):
        for a in self.res.assignments.values():
            if a.function_id == 'gen_ampl':
                self.assertEqual((a.status, a.standard, a.automation), ('assigned', '5790B', 'unverified'), a.point_id)
                self.assertEqual(a.direction, 'source')
                self.assertGreater(a.tur, 1)

    def test_frequency_goes_to_a_counter_without_numbers(self):
        a = self.res.assignments['gen_freq.r20000000.+10000000~1']
        self.assertEqual((a.status, a.standard, a.automation), ('assigned', '53132A', 'unverified'))
        self.assertIsNone(a.tur)
        cand = next(c for c in a.candidates if c.standard == '53132A')
        self.assertFalse(cand.spec_known)
        self.assertTrue(any('no specification sheet' in n for n in cand.notes))
        c8902 = next(c for c in a.candidates if c.standard == '8902A')
        self.assertFalse(c8902.covered)
        self.assertEqual(c8902.reason, 'out_of_range')
        self.assertEqual(c8902.automation, 'no')
        # the 5790B driver has no frequency measurement: never offered a driver for it
        self.assertEqual(dm.automation_status('5790B', 'GEN_FREQ').status, 'no')

    def test_offset_is_covered_by_the_5790b_spec_but_cannot_be_automated(self):
        a = self.res.assignments['gen_offset.r5.+2']
        self.assertEqual((a.status, a.standard, a.automation), ('assigned', '5790B', 'no'))
        self.assertFalse(a.can_automate)
        self.assertIn('DC mode', a.automation_note)

    def test_flatness_to_20_mhz_on_the_wideband_input(self):
        for a in self.res.assignments.values():
            if a.function_id == 'gen_flat':
                self.assertEqual((a.status, a.standard), ('assigned', '5790B'), a.point_id)
                self.assertIsNone(a.tur)                                       # dB tolerance against a volt accuracy: never converted
                self.assertTrue(any('never converted' in n for n in a.candidates[0].notes))

    def test_vpp_amplitude_converts_to_rms_exactly_and_unsupported_waveforms_say_so(self):
        ds = db.Datasheet('A', 'G', 'G')
        ds.set_periods([('1y', 'y')], '1y')
        g = ds.add_function('GEN_AMPL', settings={'waveform': 'SIN', 'amp_unit': 'Vpp'})
        g.add_range('20', '1e-3')
        ds.set_spec(g, '1 % of reading')
        p = db.add_point(g, '2.828427124746190097603377448', None, 1000)
        w = ds.add_function('GEN_AMPL', settings={'waveform': 'RAMP', 'amp_unit': 'Vpp'})
        w.add_range('20', '1e-3')
        ds.set_spec(w, '1 % of reading')
        db.add_point(w, 2, None, 1000)
        st = dm.stimulus(g, p)
        self.assertAlmostEqual(float(st.value), 1.0, 15)                       # 2.828 Vpp sine = 1 Vrms
        res = self.m.match(ds)
        self.assertEqual(res.assignments[p.id].status, 'assigned')
        bad = res.assignments[w.points[0].id]
        self.assertEqual((bad.status, bad.reason), ('uncovered', 'unsupported_waveform'))


class Scope(M):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ds = fx.scope_tds2000c_like()
        cls.res = cls.m.match(cls.ds)

    def test_dc_gain_uses_the_calibrators_dc_volts(self):
        s = self.res.summary()['scope_gain']
        self.assertEqual((s['assigned'], s['uncovered']), (8, 0))
        a = next(a for a in self.res.assignments.values() if a.function_id == 'scope_gain')
        self.assertIsNotNone(a.tur)

    def test_bandwidth_needs_the_scope_output_rows_so_only_the_5522a_qualifies(self):
        for a in self.res.assignments.values():
            if a.function_id == 'scope_bw':
                self.assertEqual((a.status, a.standard, a.automation), ('assigned', '5522A', 'unverified'), a.point_id)
                c5560 = next(c for c in a.candidates if c.standard == '5560A')
                self.assertFalse(c5560.covered)
                self.assertEqual(c5560.reason, 'no_standard_for_function')

    def test_bandwidth_above_the_calibrator_is_uncovered(self):
        ds = fx.scope_tds2000c_like()
        fn = ds.function('scope_bw')
        db.add_point(fn, 0, None, '1 GHz', '3 V')
        res = self.m.match(ds)
        a = res.assignments['scope_bw.r10.+0@1000000000~3']
        self.assertEqual((a.status, a.reason), ('uncovered', 'frequency_too_high'))
        self.assertIn('600 MHz', a.message)

    def test_time_base_and_trigger(self):
        for a in self.res.assignments.values():
            if a.function_id == 'scope_timebase':
                self.assertEqual((a.status, a.standard), ('assigned', '5522A'))
                self.assertIsNotNone(a.tur)                                    # seconds against seconds
            if a.function_id == 'scope_trigger':
                self.assertEqual(a.status, 'assigned')
                self.assertIsNone(a.tur)                                       # pass / fail: no tolerance


class Drivers(M):
    def test_driver_table_lists_every_standard_and_what_it_can_do(self):
        rows = {r['model']: r for r in dm.driver_table(DB)}
        self.assertEqual(set(rows), {'5520A', '5522A', '5560A', '5790B', '53131A', '53132A', '96270A', '8563E', '8902A'})
        self.assertEqual(rows['5522A']['driver'], 'Fluke5522A')
        self.assertEqual(rows['5522A']['scope_driver'], 'Fluke5522AScope')
        self.assertEqual(rows['5522A']['functions']['DCV']['status'], 'ok')
        self.assertEqual(rows['5522A']['functions']['CAP']['status'], 'unverified')
        self.assertEqual(rows['5560A']['functions']['SCOPE_GAIN']['status'], 'ok')
        self.assertEqual(rows['5522A']['functions']['SCOPE_GAIN']['status'], 'unverified')
        self.assertTrue(rows['53132A']['spec_pending'])
        self.assertFalse(rows['53132A']['imported'])
        self.assertTrue(rows['5522A']['imported'])
        self.assertEqual(rows['96270A']['functions'], {})
        self.assertEqual(rows['8902A']['driver'], '')

    def test_automation_status_and_text(self):
        self.assertEqual(dm.automation_text(dm.automation_status('5522A', 'DCV')), 'can automate')
        self.assertIn('not yet verified', dm.automation_text(dm.automation_status('5522A', 'CAP')))
        self.assertEqual(dm.automation_text(dm.automation_status('8902A', 'GEN_FREQ'), 'GEN_FREQ'), 'cannot automate (no driver for GEN_FREQ)')
        cap = dm.automation_status('5790B', 'DCV')
        self.assertEqual(cap.status, 'manual')
        self.assertIn('set by hand', dm.automation_text(cap, 'DCV'))
        self.assertEqual(dm.automation_status('XYZ', 'DCV').status, 'no')

    def test_every_function_kind_has_a_status_for_the_calibrators(self):
        for model in ('5522A', '5560A'):
            for kind in db.KINDS:
                if db.KINDS[kind]['family'] == 'generator':
                    continue
                self.assertIn(dm.automation_status(model, kind).status, ('ok', 'unverified'), (model, kind))

    def test_driver_classes_named_in_the_table_exist(self):
        import ast
        src = (HERE.parent / 'drivers' / '__init__.py').read_text(encoding='utf-8')
        names = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom):
                names |= {a.asname or a.name for a in node.names}
        for info in dm.DRIVER_TABLE.values():
            for cls in (info.driver, info.scope_driver):
                if cls:
                    self.assertIn(cls, names, cls)

    def test_unverified_items_are_listed_for_the_summary(self):
        self.assertTrue(dm.UNVERIFIED_ITEMS)
        self.assertTrue(any(x.startswith('5790B') for x in dm.UNVERIFIED_ITEMS))
        res = self.m.match(fx.generator_33220a_like())
        self.assertTrue(any('unverified' in n for n in res.notes))


if __name__ == '__main__':
    unittest.main()
