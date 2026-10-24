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
            self.assertEqual(r.spec.engine_printed['Uncertainty'], 'N/A')          # what the engine itself still prints
            self.assertTrue(r.applied and not r.changed)

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
            self.assertEqual(tb.count('0.050 dB'), ta.count('0.050 dB') + 3)
            import pypdf
            self.assertEqual(len(pypdf.PdfReader(str(a)).pages), len(pypdf.PdfReader(str(b)).pages))
            for token in ('Manual', 'Not in scope', 'review', '*'):
                self.assertEqual(ta.count(token), tb.count(token), token)
            rid = R.last_run_id('A-200')
            snap = rs.load(rid)
            self.assertEqual(snap.status, rs.OK)
            ch = snap.data['details']['uncertainty_review']['reviews'][0]['changes']
            self.assertEqual(sorted(c['uncertainty'] for c in ch), ['0.050 dB'] * 3)
            res = rs.regenerate(rid, choose_path=lambda n, o, p=again: str(p), confirm_overwrite=lambda p, o: False)
            self.assertTrue(res.ok, res.message)
            self.assertEqual(R.differences(b, again, None), [])
        finally:
            try:
                reg.__exit__(None, None, None)
            except Exception:
                pass


class Wiring(unittest.TestCase):
    def test_no_engine_file_edited_and_shared_modules_in_no_fingerprint(self):
        base = subprocess.run(['git', 'diff', '--name-only', 'origin/main'], cwd=ROOT, capture_output=True, text=True).stdout.split()
        self.assertEqual([f for f in base if f.endswith('_verification.py') or f.startswith('Procedures/') or f.startswith('specs/')], [])
        text = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'Procedures').glob('*.procedure.json'))
        for f in ('report_review_adapters.py', 'report_review_model.py', 'uncertainty_budget.py'):
            self.assertNotIn(f, text, f)


if __name__ == '__main__':
    unittest.main()
