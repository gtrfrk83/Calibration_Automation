"""Fluke 5520A in the per-procedure calibrator pickers (calibrator_fit.py, drivers/fluke_5560a.py Fluke5520A).

The fit is decided by the 5520A's published specification sheet (specs/standards/fluke_5520a_standard.json) through the Datasheet Builder match:
a point without a sheet row is not offered.  Pins which procedures offer the 5520A, the exact excluded points and their reasons, the LCOMP-off rule,
the Fluke5520A command registry (6 confirmed, the rest flagged UNVERIFIED) and that the 5522A / 5560A paths did not move.
tkinter is stubbed in setUpModule.   Run:  python -m unittest tests.test_calibrator_fit"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

cf = h = drivers = A34 = A88 = None


def setUpModule():
    global cf, h, drivers, A34, A88
    import _tk_stub
    _tk_stub.install()
    sys.path.insert(0, str(ROOT / 'Procedures'))
    import calibrator_fit as _cf
    import handheld_dmm as _h
    import drivers as _d
    import agilent34410a_verification as _a
    import fluke8808a_verification as _e
    cf, h, drivers, A34, A88 = _cf, _h, _d, _a, _e
    if A88.POINTS is None:
        A88.SPEC = A88.load_spec()
        A88.POINTS = A88.flatten(A88.SPEC)


def handheld_offer(spec_file, model):
    spec = h.load_spec(spec_file)
    return cf.make_offer('5520A', cf.handheld_requests(h.points_for(spec, model)))


class HandheldFit(unittest.TestCase):
    def test_110_series_and_77iv_are_offered(self):
        for f, models in (('fluke_110_series_pv.json', ('110', '113', '114', '115', '116', '117')), ('fluke_77iv_pv.json', ('77IV',))):
            for m in models:
                with self.subTest(m):
                    o = handheld_offer(f, m)
                    self.assertTrue(o.offered, o.text)
                    self.assertTrue(o.fit.complete)
                    self.assertGreater(o.fit.total, 0)

    def test_170_287_289_and_mm325_are_offered(self):
        for f in ('fluke_170_series_pv.json', 'fluke_287_289_pv.json', 'klein_mm325_pv.json'):
            spec = h.load_spec(f)
            for m in spec['models']:
                with self.subTest((f, m)):
                    o = cf.make_offer('5520A', cf.handheld_requests(h.points_for(spec, m)))
                    self.assertTrue(o.offered, o.text)

    def test_87v_not_offered_square_wave_points_named(self):
        o = handheld_offer('fluke_80_series_v_pv.json', '87V')
        self.assertFalse(o.offered)
        self.assertEqual(sorted(r.label.split(':')[0] for r, _v in o.fit.excluded), ['3-16', '3-47MAX.87', '3-47MIN.87'])
        for _r, v in o.fit.excluded:
            self.assertIn('square-wave', v.reason)
        self.assertIn('NOT offered', o.text)
        self.assertIn('3-16', o.tooltip)

    def test_picker_values_follow_the_offer(self):
        self.assertEqual(cf.picker_values(['a', 'b'], {'b': handheld_offer('fluke_80_series_v_pv.json', '87V')}), ['a'])
        self.assertEqual(cf.picker_values(['a', 'b'], {'b': handheld_offer('fluke_77iv_pv.json', '77IV')}), ['a', 'b'])


class CheckRules(unittest.TestCase):
    def test_check_never_raises_and_misses_have_a_reason(self):
        v = cf.check('5520A', cf.Req('ACV', 10.0, 300000.0))
        self.assertFalse(v.ok)
        self.assertTrue(v.reason)

    def test_dc_volts_inside_range_ok(self):
        v = cf.check('5520A', cf.Req('DCV', 1.0))
        self.assertTrue(v.ok)
        self.assertIsNotNone(v.accuracy)

    def test_square_and_duty_unsupported(self):
        for k in ('SQUARE', 'DUTY'):
            self.assertFalse(cf.check('5520A', cf.Req(k, 5.0, 1000.0)).ok)

    def test_aci_uses_lcomp_off_rows(self):
        std = cf.standard('5520A')
        self.assertEqual(cf._variant(std, 'ACI'), 'lcomp off')
        self.assertFalse(cf.check('5520A', cf.Req('ACI', 10.0, 40.0)).ok)


class Procedures34410AAnd8808A(unittest.TestCase):
    def test_34410a_excludes_exactly_the_300khz_ac_volts_points(self):
        o = cf.make_offer('5520A', cf.dmm_requests(A34.POINTS))
        self.assertFalse(o.offered)
        self.assertEqual(len(o.fit.excluded), 3)
        for r, _v in o.fit.excluded:
            self.assertEqual((r.kind, r.frequency), ('ACV', 300000.0))

    def test_34410a_picker_drops_the_5520a_and_saved_choice_falls_back(self):
        class Fake:
            cal_offer = cf.make_offer('5520A', cf.dmm_requests(A34.POINTS))
        self.assertEqual(A34.App.cal_choices(Fake), ['Fluke 5560A', 'Fluke 5522A'])

    def test_8808a_routes_five_points_to_manual(self):
        o = cf.make_offer('5520A', cf.dmm_requests(A88.POINTS), per_point_manual=True)
        self.assertTrue(o.offered)
        self.assertEqual(len(o.manual), 5)
        keys = {r.key for r, _why in o.manual}
        self.assertEqual(len(keys), 5)
        self.assertTrue(all(why for _r, why in o.manual))

    def test_8808a_picker_lists_the_5520a(self):
        class Fake:
            cal_offer = cf.make_offer('5520A', cf.dmm_requests(A88.POINTS), per_point_manual=True)
        self.assertIn('Fluke 5520A', A88.App.cal_choices(Fake))


class Fluke5520ADriver(unittest.TestCase):
    def test_registry_six_confirmed_rest_unverified(self):
        c = drivers.Fluke5520A
        ok = {k for k, v in c.COMMANDS.items() if v.verified}
        self.assertEqual(ok, {'status.clear', 'err.query', 'oper.on', 'opc.query', 'out.query', 'out.amps.dc'})
        self.assertEqual(len(c.COMMANDS), 47)
        self.assertFalse(c.COMMANDS['reset'].verified)

    def test_summary_names_the_unverified_items(self):
        s = drivers.Fluke5520A.unverified_summary()
        self.assertIn('6 of 47', s)
        self.assertIn('5520A', s)

    def test_identity_and_5522a_5560a_registries_untouched(self):
        self.assertEqual(drivers.Fluke5520A.MODEL, 'Fluke 5520A')
        self.assertEqual(drivers.Fluke5522A.MODEL, 'Fluke 5522A')
        self.assertTrue(issubclass(drivers.Fluke5520A, drivers.Fluke5522A) or issubclass(drivers.Fluke5520A, drivers.Fluke5560A))


class HandheldPickerChoices(unittest.TestCase):
    def test_choices_with_and_without_5520a(self):
        class On:
            cal_offer = handheld_offer('fluke_77iv_pv.json', '77IV')
        class Off:
            cal_offer = handheld_offer('fluke_80_series_v_pv.json', '87V')
        on, off = h.App.cal_choices(On), h.App.cal_choices(Off)
        self.assertEqual(off, list(h.CAL_CHOICES))
        self.assertIn(h.CAL_5520A_AUTO, on)
        self.assertIn(h.CAL_5520A_MANUAL, on)
        self.assertEqual([c for c in on if '5520' not in c], list(h.CAL_CHOICES))


class SimulatedRun(unittest.TestCase):
    def test_offered_procedure_sees_no_refusal_on_the_limits_simulator(self):
        from drivers.simulated import SimBench
        from drivers.simulated_5520a import Sim5520ALimitsTransport
        spec = h.load_spec('fluke_77iv_pv.json')
        pts = [p for p in h.points_for(spec, '77IV') if p.get('source', 'calibrator') == 'calibrator']
        bench = SimBench()
        t = Sim5520ALimitsTransport(bench)
        io = h.IO('Fluke 5520A', 'sim', transport=t)
        io._wait = lambda *a, **k: None
        n = 0
        for p in pts:
            try:
                io.apply(p)
                n += 1
            except Exception:                                    # a point needing an operator prompt is not an output refusal
                pass
        self.assertGreater(n, 0)
        self.assertEqual(t.refused, [])

    def test_limits_simulator_refuses_a_point_the_sheet_does_not_publish(self):
        from drivers.simulated import SimBench
        from drivers.simulated_5520a import Sim5520ALimitsTransport, request_of
        t = Sim5520ALimitsTransport(SimBench())
        t._handle('OUT 10 V, 300 KHZ')
        self.assertEqual(len(t.refused), 1)
        self.assertEqual((request_of('OUT 10 V, 300 KHZ').kind), 'ACV')


if __name__ == '__main__':
    unittest.main()
