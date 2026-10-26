"""Datasheet Builder: clamp-meter current points driven through the 50-turn coil (dsb_coil, coil_rule; NOTES.md 'STANDING RULE: clamp meters on the 50-turn coil').

The coil's own sheet (A2LA-5500A-COIL) gives the uncertainty at the EFFECTIVE current (the point's nominal) RSS with the clamp / coil interaction; the calibrator SOURCES nominal / 50 and stays
the automation standard; below the coil's range the calibrator's uncertainty at the sourced current applies with no interaction term.  The numbers must be the engine procedures' own
(iflex_option.App.unc_source, report_pdf.point_uncertainty, tartur.row_fields).  No tkinter."""
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dsb_run_harness as H  # noqa: E402,F401   (installs the tkinter stub; dsb_runtime needs it)
import coil_rule  # noqa: E402
import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_specs as dsp  # noqa: E402
import dsb_coil  # noqa: E402
import dsb_runtime as rt  # noqa: E402
import iflex_option  # noqa: E402
import report_pdf  # noqa: E402
import tartur  # noqa: E402

COIL = 'A2LA-5500A-COIL'


def sheet(coil=True):
    ds = db.Datasheet('Acme', 'CL-1', 'Clamp meter')
    ds.set_periods([('1y', 'y')], '1y')
    pts = {}
    for kind, rows in (('ACI', [(500, 50), (10, 50), (100, 50)]), ('DCI', [(10, None), (500, None)])):
        fn = ds.add_function(kind)
        fn.add_range('1000', '0.1')
        ds.set_spec(fn, '1 % of reading + 0.5 A')
        for nom, f in rows:
            p = db.add_point(fn, nom, frequency=f)
            pts[(kind, nom)] = p
            if coil and (kind, nom) != ('ACI', 100):              # ACI 100 A stays a plain (non-coil) point
                dsb_coil.set_coil(fn, p, True)
    return ds, pts


class Storage(unittest.TestCase):
    def test_flag_round_trips_and_old_sheets_are_not_coil(self):
        ds, pts = sheet()
        fn = ds.function('aci')
        self.assertTrue(dsb_coil.is_coil(fn, pts[('ACI', 500)]))
        self.assertFalse(dsb_coil.is_coil(fn, pts[('ACI', 100)]))
        back = db.Datasheet.from_dict(ds.to_dict())
        self.assertTrue(dsb_coil.is_coil(back.function('aci'), back.function('aci').point(pts[('ACI', 500)].id)))
        self.assertFalse(dsb_coil.is_coil(back.function('aci'), back.function('aci').point(pts[('ACI', 100)].id)))
        old, opts = sheet(coil=False)
        self.assertFalse(any(dsb_coil.is_coil(f, p) for f, p in old.all_points()))
        self.assertNotIn('coil', opts[('ACI', 500)].to_dict().get('settings', {}))

    def test_only_a_current_point_can_be_driven_through_the_coil(self):
        ds = db.Datasheet('Acme', 'CL-1', 'Clamp meter')
        fn = ds.add_function('DCV')
        fn.add_range('10', '0.001')
        p = db.add_point(fn, 5)
        self.assertFalse(dsb_coil.offered(fn))
        with self.assertRaises(ValueError):
            dsb_coil.set_coil(fn, p, True)
        self.assertEqual(float(dsb_coil.sourced(500)), 10.0)


class Matching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds, cls.pts = sheet()
        cls.m = dm.Matcher()
        cls.res = cls.m.match(cls.ds)

    def a(self, kind, nominal):
        return self.res.assignments[self.pts[(kind, nominal)].id]

    def test_ac_500_a_50_hz_uses_the_coil_sheet_with_the_interaction_term(self):
        a = self.a('ACI', 500)
        self.assertEqual((a.status, a.unc_standard, a.coil), ('assigned', COIL, True))
        self.assertEqual(a.uncertainty, 5.0)                                         # 0.8 % of 500 A = 4.0 A, RSS (0.50 % of 500 + 0.5) / 2 = 1.5 A: 4.27 A -> 5.0 A
        self.assertAlmostEqual(a.sourced, 10.0)
        self.assertEqual(a.standard in ('5522A', '5560A'), True)                     # the CALIBRATOR stays the automation standard
        self.assertEqual(a.automation, dm.OK)
        self.assertNotIn(COIL, [c.standard for c in a.candidates])                   # the coil is never a calibrator choice (sheet note 11)

    def test_dc_10_a_uses_the_coil_dc_row(self):
        a = self.a('DCI', 10)
        self.assertEqual((a.unc_standard, a.coil), (COIL, True))
        self.assertAlmostEqual(a.uncertainty, 0.56)                                  # (90 uA/A + 0.1 mA) = 1 mA RSS (0.5 % of 10 A + 0.5 A) / 2 = 0.275 A: 0.56 A at k = 2 rounded up
        self.assertAlmostEqual(a.sourced, 0.2)

    def test_ac_10_a_is_below_the_coils_range_so_the_calibrator_at_the_sourced_current_applies(self):
        a = self.a('ACI', 10)
        self.assertEqual((a.unc_standard, a.sourced), (a.standard, 0.2))              # the calibrator itself, at 0.2 A, no interaction term
        self.assertFalse(coil_rule.covers('ACI', 10.0, 50.0))
        cand = next(c for c in a.candidates if c.standard == a.standard)
        self.assertEqual(a.uncertainty, cand.uncertainty)
        self.assertLess(a.uncertainty, 0.01)                                         # a 0.2 A calibrator figure, not the coil's several amperes

    def test_a_non_coil_current_point_is_unchanged(self):
        a = self.a('ACI', 100)
        self.assertFalse(a.coil)
        self.assertEqual((a.unc_standard, a.sourced), ('', None))
        self.assertNotIn('coil', a.to_dict())
        self.assertNotIn('unc_standard', a.to_dict())
        plain, pp = sheet(coil=False)
        same = self.m.match(plain).assignments[pp[('ACI', 100)].id]
        self.assertEqual((a.standard, a.uncertainty, a.tur), (same.standard, same.uncertainty, same.tur))

    def test_a_coil_point_works_in_the_matching_numbers_of_the_engine_procedures(self):
        """The figures equal iflex_option.App.unc_source + report_pdf.point_uncertainty + tartur.row_fields for the same point."""
        for kind, nominal, freq in (('ACI', 500, 50.0), ('DCI', 10, None), ('DCI', 500, None), ('ACI', 10, 50.0)):
            pt = self.pts[(kind, nominal)]
            fn = self.ds.function(kind.lower())
            a = self.a(kind, nominal)
            lim = fn.limit_for(pt, '1y', self.ds)
            step = dict(kind=kind, nominal=float(nominal), unc_standard=COIL, unc_nominal=float(nominal), applied=dict(value=float(nominal) / 50, frequency=freq), base_unit='A')
            nom, std = iflex_option.App.unc_source(step)
            extra = iflex_option.App.unc_extra(step)
            q = dict(kind=kind, nominal=nom, frequency=freq, unit='A', range=None, extra=extra)
            fields = tartur.row_fields(q, float(lim.low), float(lim.high), standard=std or a.standard)
            if std:                                                                  # the coil covers it
                self.assertEqual(a.unc_standard, COIL, (kind, nominal))
                printed = report_pdf.point_uncertainty(q, standard=std)
                import uncertainty
                self.assertEqual(uncertainty.format_value(a.uncertainty, 'A'), printed, (kind, nominal))
                self.assertEqual(tartur.format_ratio(a.tur), fields['TUR'], (kind, nominal))
                self.assertEqual(tartur.format_ratio(a.tar), fields['TAR'], (kind, nominal))
            else:                                                                    # below the coil's range: the calibrator at the sourced current
                self.assertEqual(a.unc_standard, a.standard)
                self.assertEqual(nom, float(nominal) / 50)


class Export(unittest.TestCase):
    def test_the_spec_sources_nominal_over_50_names_the_coil_and_carries_the_hookup_text(self):
        ds, pts = sheet()
        res = dsp.export_spec(ds)
        self.assertTrue(res.ok, [str(x) for x in res.problems])
        steps = {s['dsb']['point_id']: s for s in res.spec['steps']}
        s = steps[pts[('ACI', 500)].id]
        self.assertEqual((s['applied']['value'], s['nominal'], s['coil'], s['unc_standard'], s['unc_nominal']), (10.0, 500.0, 50, COIL, 500.0))
        self.assertEqual(s['applied']['frequency'], 50.0)
        self.assertEqual(s['group'], 'COIL_20A')                                      # 10 A: the calibrator's high-current output
        self.assertEqual(steps[pts[('DCI', 10)].id]['group'], 'COIL_AUX')              # 0.2 A: the low-current output
        self.assertEqual(steps[pts[('DCI', 10)].id]['applied']['value'], 0.2)
        plain = steps[pts[('ACI', 100)].id]
        self.assertEqual(plain['applied']['value'], 100.0)                           # a non-coil point is exactly as before
        self.assertNotIn('coil', plain)
        self.assertEqual(set(res.spec['groups']), {'COIL_AUX', 'COIL_20A'})
        self.assertIn('50-turn coil', res.spec['groups']['COIL_AUX']['title'])
        self.assertTrue(any('Standby' in t for t, _x in res.spec['groups']['COIL_AUX']['steps']))
        none, _p = sheet(coil=False)
        self.assertNotIn('groups', dsp.export_spec(none).spec)

    def test_the_runtime_reads_the_coil_figures_like_the_engine_procedures(self):
        ds, pts = sheet()
        spec = dsp.export_spec(ds).spec
        points = rt.runtime_points(spec, ds.model)
        by = {p['dsb']['point_id']: p for p in points}
        app = SimpleNamespace(demo=False, has_uncertainty=rt.DsbApp.has_uncertainty)
        app.unc_source = lambda p: rt.DsbApp.unc_source(app, p)
        covered = lambda p: rt.DsbApp.coil_covered(app, p)                            # noqa: E731
        self.assertEqual(app.unc_source(by[pts[('ACI', 500)].id]), iflex_option.App.unc_source(by[pts[('ACI', 500)].id]))
        self.assertTrue(covered(by[pts[('ACI', 500)].id]))
        self.assertTrue(covered(by[pts[('DCI', 10)].id]))
        self.assertFalse(covered(by[pts[('ACI', 10)].id]))                           # below the coil's range: the calibrator's own figures
        self.assertFalse(covered(by[pts[('ACI', 100)].id]))                          # not a coil point
        self.assertEqual(rt.DsbApp.unc_extra(app, by[pts[('ACI', 500)].id]), iflex_option.App.unc_extra(by[pts[('ACI', 500)].id]))
        self.assertEqual(rt.DsbApp.unc_extra(app, by[pts[('ACI', 10)].id]), ())
        app.demo = True
        self.assertFalse(covered(by[pts[('ACI', 500)].id]))                          # a demo never prints a standard's figures
        self.assertIn('50-turn coil', by[pts[('ACI', 500)].id]['dsb_desc'])


if __name__ == '__main__':
    unittest.main()
