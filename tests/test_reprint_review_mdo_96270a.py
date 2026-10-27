"""MDO4000C RF level (absolute amplitude / flatness) rows take their uncertainty from the Fluke 96270A standard sheet (owner decision), through the review window.

Hand values come from specs/standards/fluke_96270a_standard.json, 'RF Level Accuracy (into 50 ohm) [Leveling Head O/P]', rows 'down to -48 dBm':
0-100 kHz +/-0.03 dB, 100 kHz-128 MHz +/-0.05 dB, 4 GHz +/-0.3 dB (Technical Data 6002252B_EN p.6).  No confidence level is printed: k = 2 assumed.
Phase noise has NO row on the sheet (a 'typical' note only): those rows stay 'Not in scope'.  Crosstalk, reference frequency and TPA-N-PRE rows are untouched.
Run:  python -m unittest tests.test_reprint_review_mdo_96270a
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import reprint_harness as R  # noqa: E402
import ui_ported  # noqa: E402
import phase2_apps as P  # noqa: E402
import report_review_adapters as A  # noqa: E402
import report_review_model as M  # noqa: E402
import report_snapshot as rs  # noqa: E402
import test_reprint_review_phase2 as T2  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

HAVE = T2.HAVE


class Budget(unittest.TestCase):
    def test_bands_by_hand(self):
        b = ub.rf_level(10.0, [50e3])                         # 0-100 kHz band: 0.03 dB / 2 = 0.015; EMU = 2 x 0.015 = 0.03
        self.assertAlmostEqual(b.components[0].u, 0.015, 12)
        self.assertAlmostEqual(b.emu, 0.03, 12)
        self.assertEqual(b.reported, 0.03)
        b = ub.rf_level(10.0, [50e3, 150e3, 950e3])           # the 50 kHz - 950 kHz sweep crosses both bands: the larger, 0.05 dB
        self.assertAlmostEqual(b.emu, 0.05, 12)
        self.assertEqual(b.reported, 0.05)
        self.assertEqual(ub.rf_level(0.0, [100e3]).reported, 0.05)          # exactly on the 100 kHz border: the larger limit
        self.assertEqual(ub.rf_level(-15.0, [10e6, 90e6]).reported, 0.05)
        self.assertEqual(ub.rf_level(10.0, [4e9]).reported, 0.3)            # the single 4 GHz point

    def test_not_covered_is_none_never_extrapolated(self):
        self.assertIsNone(ub.rf_level(10.0, [100e6, 200e6]))               # nothing printed between 128 MHz and 4 GHz
        self.assertIsNone(ub.rf_level(10.0, [3.1e9]))
        self.assertIsNone(ub.rf_level(-60.0, [1e6]))                       # below the 'down to -48 dBm' rows
        self.assertIsNone(ub.rf_level(10.0, []))

    def test_floor_only_where_the_scope_has_an_entry(self):
        self.assertIsNone(ub.rf_level(10.0, [1e6]).cmc)                    # the lab scope has no RF level entry: no floor
        self.assertEqual(ub.rf_level(10.0, [1e6], cmc=0.08).reported, 0.08)   # a CMC above the budget is reported
        self.assertEqual(ub.rf_level(10.0, [1e6], cmc=0.01).reported, 0.05)   # a CMC below it changes nothing
        self.assertEqual(ub.rf_level(10.0, [1e6], cmc=0.0512).reported, 0.052)  # rounded UP, 2 s.f.


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class Review(unittest.TestCase):
    def rows(self):
        app, mod = T2.built('mdo')
        specs, d = M.specs_for(app)
        return app, mod, M.ReviewModel(specs, d, asset='A-200')

    def test_flatness_rows_are_96270a(self):
        _a, _m, model = self.rows()
        flat = [r for r in model.rows if r.spec.q['kind'] == 'ABSAMP']
        self.assertEqual(len(flat), 3)
        for r in flat:
            self.assertEqual((r.standard, r.status, r.reported_text, r.tar_text, r.tur_text), ('96270A', M.AS_BUDGETED, '0.050 dB', '20.0:1', '20.0:1'), r.spec.description)
            self.assertEqual(r.spec.options, ['96270A'])
            self.assertEqual(M.offered_standards(r.spec), ['96270A'])
            self.assertAlmostEqual(r.cur.budget, 0.05, 12)
            self.assertIsNone(r.cur.cmc)
            self.assertFalse(r.can_type())
            self.assertEqual(r.spec.engine_printed['Uncertainty'], '0.050 dB')     # the engine itself prints the same figure now
            self.assertFalse(r.applied or r.changed)

    def test_uncovered_flatness_and_phase_noise_stay_not_in_scope(self):
        import mdo4000c_verification as mod
        specs = []
        for p in mod.POINTS:                                                     # all 15 flatness rows, covered or not
            if p['kind'] == 'ABSAMP':
                specs.append((p['desc'], A._rf_budget(p) is not None))
        self.assertEqual(sum(1 for _d, ok in specs if ok), 9)                    # 50k-950k, 1-9 MHz, 10-90 MHz at +10 / 0 / -15 dBm
        self.assertTrue(all((not ok) for d, ok in specs if '100 MHz' in d or '>3 GHz' in d))
        _a, _m, model = self.rows()
        ph = [r for r in model.rows if r.spec.q['kind'] == 'PHASE']
        self.assertEqual(len(ph), 3)
        for r in ph:
            self.assertEqual((r.status, r.reported_text, r.tur_text, r.spec.options), (M.NOT_IN_SCOPE, 'N/A', '', None))
            self.assertTrue(r.can_type())
        for kind in ('XTALK', 'REFFREQ', 'TPAFUNC'):
            for r in model.rows:
                if r.spec.q['kind'] == kind:
                    self.assertIsNone(r.spec.engine_printed)
                    self.assertEqual(r.reported_text, r.spec.printed['Uncertainty'])

    def test_pdf_snapshot_regenerate(self):
        app, mod, model = self.rows()
        d = Path(tempfile.mkdtemp())
        a, b, again = d / 'a.pdf', d / 'b.pdf', d / 'again.pdf'
        reg = R.registry()
        try:
            T2.export('mdo', app, mod, a, R.DETAILS)
            T2.export('mdo', app, mod, b, dict(R.DETAILS, uncertainty_review=M.review_block([model], 'Tech', '2026-01-01T00:00:00')))
            ta, tb = R.pdf_text(a), R.pdf_text(b)
            self.assertEqual(R.differences(a, b, None), [])                          # engine alone == unchanged review
            self.assertEqual(ta, tb)
            self.assertGreaterEqual(ta.count('0.050 dB'), 3)
            import pypdf
            self.assertEqual(len(pypdf.PdfReader(str(a)).pages), len(pypdf.PdfReader(str(b)).pages))
            for token in ('Manual', 'Not in scope', 'review', '*'):
                self.assertEqual(ta.count(token), tb.count(token), token)
            rid = R.last_run_id('A-200')
            snap = rs.load(rid)
            self.assertEqual(snap.status, rs.OK)
            rows = snap.data.get('rows') or []
            self.assertEqual(snap.data['details']['uncertainty_review']['reviews'][0]['changes'], [])
            res = rs.regenerate(rid, choose_path=lambda n, o, p=again: str(p), confirm_overwrite=lambda p, o: False)
            self.assertTrue(res.ok, res.message)
            self.assertEqual(R.differences(b, again, None), [])
        finally:
            try:
                reg.__exit__(None, None, None)
            except Exception:
                pass


class Engine(unittest.TestCase):
    def test_engine_prints_the_budget_for_covered_rows_only(self):
        import mdo4000c_verification as mod
        for p in mod.POINTS:
            if p['kind'] != 'ABSAMP':
                continue
            ok = ub.rf_level_sweep(p) is not None
            self.assertEqual(mod.uncertainty_text(p, {}), '0.050 dB' if ok else 'N/A', p['desc'])
            f = mod.tar_tur_fields(p, dict(raw={}, result='PASS', uncertainty=mod.uncertainty_text(p, {})))
            self.assertEqual((f['TAR'], f['TUR']), ('20.0:1', '20.0:1') if ok else ('', ''), p['desc'])
        for p in mod.POINTS:                                   # nothing else changed
            if p['kind'] in ('PHASE', 'XTALK', 'REFFREQ', 'TPAFUNC', 'IMD'):
                self.assertEqual(mod.uncertainty_text(p, {}), 'N/A', p['desc'])


class Wiring(unittest.TestCase):
    def test_no_engine_file_edited_and_shared_modules_in_no_fingerprint(self):
        base = subprocess.run(['git', 'diff', '--name-only', 'origin/main'], cwd=ROOT, capture_output=True, text=True).stdout.split()
        later = ('mdo4000c_verification.py', 'specs/build_mdo_spec.py', 'specs/tektronix_mdo4000c_pv.json')       # edited by the logic probe removal, not by this work
        later += ('specs/a2la_1888_03_cmc.json', 'specs/build_a2la_cmc_temperature.py',     # scope CMC thermocouple / capacitance lines (3b30fe7, dccc414)
                  'specs/build_28x_spec.py', 'specs/fluke_287_289_pv.json',                  # 287/289 panel picture, FREQ CMC on 4-24/4-25 (20edb7d, dccc414, 8b150e7)
                  'specs/build_hookups.py', 'specs/build_hookups_ext.py',                    # drawn hook-up diagrams (8b150e7); none of these is this work
                  'specs/build_a2la_cmc_flatness.py',                                        # scope AC Flatness lines (owner, 2026-10-25)
                  'specs/build_a2la_cmc_rtd.py',                                             # scope RTD lines (owner, 2026-10-25)
                  'tbs1000_verification.py', 'specs/README.txt',                             # Tektronix TBS1000 / TBS1000C procedures (branch tektronix-tbs1000)
                  'Procedures/Tektronix_TBS1000C_Verification.py', 'Procedures/Tektronix_TBS1000C_Verification.procedure.json',
                  'Procedures/Tektronix_TBS1000_Verification.py', 'Procedures/Tektronix_TBS1000_Verification.procedure.json',
                  'specs/build_tbs1000c_spec.py', 'specs/tektronix_tbs1000c_pv.json', 'specs/build_tbs1000_spec.py', 'specs/tektronix_tbs1000_pv.json')
        later += ('mdo3_verification.py', 'Procedures/Tektronix_MDO3_Verification.py', 'Procedures/Tektronix_MDO3_Verification.procedure.json', 'specs/README.txt',     # the 3 Series MDO procedure (branch tektronix-mdo3); not this work
                  'specs/build_mdo3_spec.py', 'specs/tektronix_mdo3_pv.json', 'specs/mdo3_reference_cmc.json')
        later += ('tbs2000b_verification.py', 'Procedures/Tektronix_TBS2000B_Verification.py', 'Procedures/Tektronix_TBS2000B_Verification.procedure.json',   # the TBS2000B procedure (branch tektronix-tbs2000b)
                  'specs/build_tbs2000b_spec.py', 'specs/tektronix_tbs2000b_pv.json',
                  'specs/build_5560a_standard_from_manual.py', 'specs/analyze_5560a_spec_check.py', 'specs/fluke_5560a_spec_check.md',          # the 5560A sheet re-run from the manual (branch fluke-5560a-spec-check)
                  'specs/standards/fluke_5560a_standard.json')
        later += ('specs/build_fluke_376_spec.py', 'specs/fluke_376_pv.json', 'Procedures/Fluke_374_Verification.py', 'Procedures/Fluke_375_Verification.py', 'Procedures/Fluke_376_Verification.py', 'Procedures/Fluke_376II_Verification.py',
                  'i400_verification.py', 'Procedures/Fluke_i400_Verification.py', 'Procedures/Fluke_i400_Verification.procedure.json', 'specs/build_fluke_i400_spec.py', 'specs/fluke_i400_pv.json',
                  'specs/build_fluke_365_spec.py', 'specs/fluke_365_pv.json', 'Procedures/Fluke_323_Verification.py', 'Procedures/Fluke_323_Verification.procedure.json', 'Procedures/Fluke_324_Verification.py', 'Procedures/Fluke_324_Verification.procedure.json', 'Procedures/Fluke_325_Verification.py', 'Procedures/Fluke_325_Verification.procedure.json', 'Procedures/Fluke_753_Verification.py', 'Procedures/Fluke_753_Verification.procedure.json', 'Procedures/Fluke_754_Verification.py', 'Procedures/Fluke_754_Verification.procedure.json', 'fluke_753_754.py', 'specs/build_fluke_753_754_spec.py', 'specs/fluke_753_754_pv.json', 'specs/build_hookups_753.py', 'specs/build_fluke_323_spec.py', 'specs/fluke_323_pv.json')                                                                  # the 50-turn coil uncertainty rule (2026-10-26)
        self.assertEqual([f for f in base if (f.endswith('_verification.py') or f.startswith('Procedures/') or f.startswith('specs/')) and f not in later and f not in ui_ported.files()], [])
        text = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'Procedures').glob('*.procedure.json'))
        for f in ('report_review_adapters.py', 'report_review_model.py', 'uncertainty_budget.py'):
            self.assertNotIn(f, text, f)


if __name__ == '__main__':
    unittest.main()
