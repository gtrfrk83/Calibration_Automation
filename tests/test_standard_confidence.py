"""Confidence level / coverage divisor of every standard sheet (the 'confidence rule', NOTES.md).

The laboratory reports expanded uncertainty at 95 % (k = 2).  A standard's published accuracy becomes a standard uncertainty by dividing by the divisor of
the confidence level the SHEET'S NUMBERS are printed at: 99 % -> 2.576, 95 % -> 2.0.  A manufacturer that prints only one level (and says which) gives that
level; one that prints a 95 % column (5560A) -> that column is stored, divisor 2.  A sheet that states no level keeps divisor 2 (laboratory convention) and
must be listed as such below.  TAR never uses a divisor.  These tests fail if a sheet's level / divisor disagrees with the table, or if a new sheet is added
without a decision.

Run:  python -m unittest tests.test_standard_confidence
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import specmanager as sm  # noqa: E402
import tartur  # noqa: E402
import uncertainty  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

# model -> (stored confidence_pct, divisor).  None = the sheet / manual prints no level (divisor 2, laboratory convention).
EXPECTED = {
    '5522A': (99.0, 2.576),    # Operators Manual printed p. 1-8: "Specification Confidence Interval 99 %" (single column)
    '5520A': (99.0, 2.576),    # Service Manual printed p. 1-7: "Specification Confidence Interval 99 %" (single column)
    '5560A': (95.0, 2.0),      # Product Specifications: 99 % (k = 2.58) AND 95 % (k = 2) columns; the stored numbers are the 95 % column
    '5790B': (99.0, 2.576),    # Operators Manual printed p. 1-9: 99 %, k = 2.58 (one 50 MHz /AF row is 95 %, see note 20 of the sheet)
    '8563E': (None, 2.0),      # no level printed
    '96270A': (None, 2.0),     # no level printed
    '8902A': (None, 2.0),      # no level printed
    'A2LA-LIGHT': (95.0, 2.0),  # the lab's own A2LA CMC (scope footnote 2: expanded, approximately 95 %, usually k = 2)
}
TABLE = {99.0: 2.576, 95.0: 2.0, None: 2.0}


def sheets():
    out = {}
    for f in sorted((ROOT / 'specs' / 'standards').glob('*_standard.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        out[d['standard']['model']] = d
    return out


class Rule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.sheets = sheets()

    def test_every_sheet_has_a_decision(self):
        self.assertEqual(sorted(self.sheets), sorted(EXPECTED), 'a standard sheet was added or removed: decide its confidence level and add it to EXPECTED')

    def test_stored_level_and_divisor_follow_the_rule(self):
        for model, (pct, div) in EXPECTED.items():
            with self.subTest(model=model):
                self.assertEqual(self.sheets[model]['standard']['confidence_pct'], pct)
                self.assertEqual(TABLE[pct], div)                       # the table itself is the rule
                s = sm.standard(model, self.db)
                self.assertEqual(s.info['confidence_pct'], pct)
                self.assertAlmostEqual(s.divisor()[0], div, 9)

    def test_no_sheet_carries_an_explicit_divisor_override(self):
        for model in EXPECTED:
            self.assertIsNone(sm.standard(model, self.db).info['divisor'], model)

    def test_calibrators_the_lab_uses_agree_with_the_manuals(self):
        for model in ('5522A', '5520A'):
            self.assertAlmostEqual(sm.standard(model, self.db).divisor()[0], 2.576, 9)         # manufacturer prints 99 %
        self.assertAlmostEqual(sm.standard('5560A', self.db).divisor()[0], 2.0, 9)             # the 95 % column is stored
        self.assertIn('99', json.dumps(self.sheets['5522A']['standard']['confidence_text']))

    def test_5522a_spec_numbers_were_not_touched(self):
        """Only the metadata changed: same number of spec rows and the same hand-checked limits as before the change (1 yr)."""
        s = sm.standard('5522A', self.db)
        self.assertEqual(len(s.rows), 545)
        self.assertAlmostEqual(s.lookup('DCV', 10.0).limit, 140e-6, 12)
        self.assertAlmostEqual(s.lookup('ACV', 1.0, frequency=1000.0).limit, 210e-6, 12)
        self.assertAlmostEqual(s.lookup_temperature(100).limit, 0.16, 12)


class Impact(unittest.TestCase):
    """5522A budget and TUR with the old divisor (2.0 forced) and the sheet's 99 % (2.576); TAR identical."""

    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.sc = uncertainty.load()
        cls.sid = sm.standard('5522A', cls.db).id

    def std(self, div):
        sm.set_standard_field(self.sid, 'divisor', div, who='test', reason='old divisor' if div else 'sheet', path=self.db)
        return sm.standard('5522A', self.db)

    def test_standard_uncertainty_ratio_is_2_over_2576(self):
        old = ub.build('DCV', 5.0, 'V', standard=self.std(2.0), scope=self.sc)
        new = ub.build('DCV', 5.0, 'V', standard=self.std(None), scope=self.sc)
        self.assertAlmostEqual(new.components[0].u / old.components[0].u, 2.0 / 2.576, 12)
        self.assertLess(new.emu, old.emu)
        self.assertGreaterEqual(new.reported, new.cmc)                                       # never below the scope CMC
        self.assertGreaterEqual(new.reported, new.emu)

    def test_tar_is_unchanged_and_tur_follows_the_printed_uncertainty(self):
        p = dict(kind='ACV', nominal=1.0, unit='V', range=None, frequency=1000.0)
        lo, hi = 1.0 - 0.0045, 1.0 + 0.0045
        r_old = tartur.compute(p, lo, hi, self.std(2.0), self.sc)
        r_new = tartur.compute(p, lo, hi, self.std(None), self.sc)
        self.assertEqual(r_old['tar'], r_new['tar'])
        self.assertEqual(r_old['accuracy'], r_new['accuracy'])
        self.assertLessEqual(r_new['uncertainty'], r_old['uncertainty'])
        self.assertGreaterEqual(r_new['tur'], r_old['tur'])
        self.assertAlmostEqual(r_new['tur'], r_new['tolerance'] / r_new['uncertainty'], 12)


class OlderDatabase(unittest.TestCase):
    """A lab_registry.sqlite3 made before the 5522A sheet had its level: seed() skips the loaded model, sync_confidence() fills the missing level."""

    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=self.db)
        self.sid = sm.standard('5522A', self.db).id
        with sqlite3.connect(self.db) as con:                                                # put the database back as it was before the change
            con.execute("UPDATE standards SET confidence_pct=NULL, confidence_text='[Not Specified]' WHERE id=?", (self.sid,))
        sm._CONF_SYNCED.discard(self.db)

    def test_missing_level_is_filled_and_logged(self):
        self.assertEqual(sm.sync_confidence(path=self.db), 1)
        s = sm.standard('5522A', self.db)
        self.assertEqual(s.info['confidence_pct'], 99.0)
        self.assertAlmostEqual(s.divisor()[0], 2.576, 9)
        self.assertTrue(any(r[2] == 'confidence_pct' and r[1] == 'sync' for r in sm.log_for(self.sid, path=self.db)))
        self.assertEqual(sm.sync_confidence(path=self.db), 0)                                # idempotent

    def test_standard_lookup_applies_it_once(self):
        s = sm.standard('5522A', self.db)
        self.assertEqual(s.info['confidence_pct'], 99.0)

    def test_explicit_divisor_and_existing_level_are_never_overwritten(self):
        sm.set_standard_field(self.sid, 'divisor', 1.96, who='t', reason='lab choice', path=self.db)
        sm.sync_confidence(path=self.db)
        self.assertEqual(sm.standard('5522A', self.db).divisor()[0], 1.96)                   # an explicit divisor still wins
        sm.set_standard_field(self.sid, 'confidence_pct', 95.0, who='t', reason='lab choice', path=self.db)
        sm.set_standard_field(self.sid, 'divisor', None, path=self.db)
        self.assertEqual(sm.sync_confidence(path=self.db), 0)
        self.assertEqual(sm.standard('5522A', self.db).info['confidence_pct'], 95.0)

    def test_only_metadata_is_touched(self):
        n_before = len(sm.standard('5522A', self.db).rows)
        sm.sync_confidence(path=self.db)
        self.assertEqual(len(sm.standard('5522A', self.db).rows), n_before)


class ReprintKeepsIssuedUncertainty(unittest.TestCase):
    """Reports already issued are NOT changed by a later change of the 5522A divisor.  A saved snapshot stores the printed rows (strings) and is printed again
    from them; nothing is recomputed.  An event without a snapshot is rebuilt from history rows with the Uncertainty cells BLANK, never recomputed."""

    def setUp(self):
        import subprocess
        from unittest import mock
        sys.path.insert(0, str(ROOT / 'tests'))
        self.skip = subprocess.run(['pdftotext', '-v'], capture_output=True).returncode not in (0, 99)
        try:
            import reportlab, pypdf  # noqa: F401
        except ImportError:
            self.skip = True
        if self.skip:
            self.skipTest('reportlab, pypdf and pdftotext are needed')
        import reprint_harness as R
        self.R = R
        d = tempfile.mkdtemp()
        self.dir = Path(d)
        self.sm_db = os.path.join(d, 'standards.sqlite3')
        patch = mock.patch.object(sm, 'DB', self.sm_db)
        patch.start()
        self.addCleanup(patch.stop)
        sm.seed()
        self.sid = sm.standard('5522A').id
        ctx = R.registry()
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def points(self):
        return [dict(kind='DCV', nominal=5.0, unit='V', range=None, error=0.0025), dict(kind='ACV', nominal=1.0, unit='V', range=None, frequency=1000.0, error=0.0045)]

    def rows(self):
        import report_pdf
        return [report_pdf.point_row(p, p['nominal'], False, standard='5522A') for p in self.points()]

    def test_snapshot_reprint_is_unchanged_but_a_new_report_is_not(self):
        import report_pdf
        import report_snapshot as rs
        R = self.R
        sm.set_standard_field(self.sid, 'divisor', 2.0, who='test', reason='state before the change')
        old_rows = self.rows()
        pdf = self.dir / 'orig.pdf'
        report_pdf.write_calibration_pdf(str(pdf), old_rows, header=[('Instrument', 'Fluke 87V'), ('Instrument ID', 'A-100'), ('Serial', 'SN1')], details=dict(R.DETAILS))
        rid = R.last_run_id('A-100')
        self.assertEqual(rs.load(rid).status, rs.OK)
        sm.set_standard_field(self.sid, 'divisor', None, who='test', reason='the sheet level (99 %) applies')      # the change
        new_rows = self.rows()
        self.assertNotEqual([r['Uncertainty'] for r in old_rows], [r['Uncertainty'] for r in new_rows], 'a report issued now carries the new uncertainties')
        out = self.dir / 'reprint.pdf'
        res = rs.regenerate(rid, choose_path=lambda name, original: str(out), confirm_overwrite=lambda p, o: False)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.kind, rs.SNAPSHOT)
        self.assertEqual(R.differences(pdf, out, None), [], 'the reprint of an issued report is identical to the original')
        self.assertEqual([r['Uncertainty'] for r in rs.load(rid).data['rows']], [r['Uncertainty'] for r in old_rows])

    def test_rebuilt_from_history_never_recomputes_uncertainty(self):
        import report_pdf
        import report_snapshot as rs
        R = self.R
        report_pdf.write_calibration_pdf(str(self.dir / 'orig.pdf'), self.rows(), header=[('Instrument', 'Fluke 87V'), ('Instrument ID', 'A-100'), ('Serial', 'SN1')],
                                         details=dict(R.DETAILS))
        rid = R.last_run_id('A-100')
        with rs._db() as con:
            con.execute('DELETE FROM report_snapshots WHERE run_id=?', (rid,))
        data, run, problem = rs.rebuild_from_history(rid)
        self.assertEqual(problem, '')
        self.assertEqual([r['Uncertainty'] for r in data['rows']], ['', ''])


if __name__ == '__main__':
    unittest.main()
