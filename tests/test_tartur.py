"""Run:  python -m unittest tests.test_tartur   (no tkinter needed: numbers are tested, not SI text)"""
import math, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import specmanager as sm
import tartur
import uncertainty
import uncertainty_budget as ub

DB = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sm.seed(path=DB)
        cls.std = sm.standard('5560A', DB)
        cls.sc = uncertainty.load()

    def dcv10(self, **k):
        return dict(kind='DCV', nominal=10.0, unit='V', range=10.0, **k)

    def test_hand_worked_10v_5560a(self):
        # limits 10 V +/- 350 uV -> T = 350 uV.  5560A 12 V range, 1 yr: 7.2e-5 V (specmanager).  Scope CMC 8.4e-5 V; budget
        # EMU = 2 * 7.2e-5 / 2 = 7.2e-5 V (no resolution term), so reported = max(7.2e-5, 8.4e-5) = 8.4e-5 V.
        r = tartur.compute(self.dcv10(), 10 - 350e-6, 10 + 350e-6, self.std, self.sc)
        self.assertAlmostEqual(r['tolerance'], 350e-6, 12)
        self.assertAlmostEqual(r['accuracy'], 72e-6, 12)
        self.assertAlmostEqual(r['uncertainty'], 84e-6, 12)
        self.assertAlmostEqual(r['tar'], 350 / 72, 6)          # 4.8611
        self.assertAlmostEqual(r['tur'], 350 / 84, 6)          # 4.1666
        self.assertEqual(tartur.format_ratio(r['tar']), '4.8:1')
        self.assertEqual(tartur.format_ratio(r['tur']), '4.1:1')      # 4.1666 rounds DOWN, not to 4.2
        self.assertEqual(r['reason'], '')

    def test_uncertainty_is_the_printed_one(self):
        b = ub.build('DCV', 10.0, 'V', standard=self.std, scope=self.sc, range_value=10.0)
        r = tartur.compute(self.dcv10(), 9.99, 10.01, self.std, self.sc)
        self.assertEqual(r['uncertainty'], b.reported)
        self.assertAlmostEqual(r['tur'], 0.01 / b.reported, 9)

    def test_without_calibrator_uses_scope_cmc_rounded_up(self):
        r = tartur.compute(self.dcv10(), 9.9995, 10.0005, None, self.sc)
        self.assertIsNone(r['tar'])
        self.assertIsNone(r['accuracy'])
        self.assertEqual(r['uncertainty'], uncertainty.round_up(8.4e-5))
        self.assertAlmostEqual(r['tur'], 0.0005 / 8.4e-5, 6)
        self.assertEqual(tartur.format_ratio(r['tur']), '5.9:1')      # 5.952 rounded down

    def test_blank_cases(self):
        lim = (9.99, 10.01)
        blank = lambda r: self.assertTrue(r['tar'] is None and r['tur'] is None and r['reason'])
        blank(tartur.compute(self.dcv10(zero_offset=True), *lim, self.std, self.sc))
        blank(tartur.compute(self.dcv10(source='none'), *lim, self.std, self.sc))
        blank(tartur.compute(self.dcv10(), 9.99, None, self.std, self.sc))        # one-sided
        blank(tartur.compute(self.dcv10(), None, 10.01, self.std, self.sc))
        blank(tartur.compute(self.dcv10(), 10.0, 10.0, self.std, self.sc))        # zero width
        blank(tartur.compute(self.dcv10(), 10.01, 9.99, self.std, self.sc))       # reversed
        blank(tartur.compute(self.dcv10(), float('nan'), 10.01, self.std, self.sc))
        blank(tartur.compute(dict(self.dcv10(), unit='%'), 0, 1, self.std, self.sc))
        blank(tartur.compute(dict(self.dcv10(), unit='dB'), -1, 1, self.std, self.sc))
        blank(tartur.compute(dict(kind='DCV', nominal=5000.0, unit='V', range=1000.0), 4990, 5010, self.std, self.sc))   # outside scope
        blank(tartur.compute({'kind': 'DCV'}, 1, 2))                               # malformed point: no raise
        blank(tartur.compute(None, 1, 2))

    def test_row_fields(self):
        self.assertEqual(tartur.row_fields(self.dcv10(), 10 - 350e-6, 10 + 350e-6, self.std), dict(TAR='4.8:1', TUR='4.1:1'))
        self.assertEqual(tartur.row_fields(self.dcv10(zero_offset=True), 0, 1, self.std), dict(TAR='', TUR=''))
        self.assertEqual(tartur.row_fields(None, 0, 1), dict(TAR='', TUR=''))

    def test_format_ratio(self):
        f = tartur.format_ratio
        self.assertEqual(f(4.2), '4.2:1')
        self.assertEqual(f(4.199999999999), '4.2:1')       # float noise
        self.assertEqual(f(4.19), '4.1:1')
        self.assertEqual(f(4.99), '4.9:1')
        self.assertEqual(f(10), '10.0:1')
        self.assertEqual(f(1000), '1000.0:1')
        self.assertEqual(f(1000.5), '>1000:1')
        self.assertEqual(f(0.54), '0.5:1')
        self.assertEqual(f(0.04), '<0.1:1')
        for bad in (None, 0, -1, float('inf'), float('nan'), 'x', True):
            self.assertEqual(f(bad), '')

    def test_never_rounds_up(self):
        for x in (1.01, 2.99, 4.15, 7.0999, 99.95, 123.456):
            s = tartur.format_ratio(x)
            self.assertLessEqual(float(s.split(':')[0]), x + 1e-9)

    def test_tur_not_above_tar_when_uncertainty_at_least_accuracy(self):
        pts = [('DCV', 0.1, None), ('DCV', 10, None), ('DCV', 100, None), ('ACV', 1, 1e3), ('ACV', 10, 10e3), ('DCI', 0.01, None), ('OHM', 100, None)]
        n = 0
        for kind, v, f in pts:
            unit = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'OHM': 'ohm'}[kind]
            p = dict(kind=kind, nominal=v, unit=unit, range=v, frequency=f)
            r = tartur.compute(p, v * 0.99, v * 1.01, self.std, self.sc)
            if r['tar'] is None or r['tur'] is None:
                continue
            n += 1
            if r['uncertainty'] >= r['accuracy']:
                self.assertLessEqual(r['tur'], r['tar'] + 1e-12, (kind, v))
        self.assertGreaterEqual(n, 4)

    def test_definition_text(self):
        t = tartur.definition_text()
        for word in ('TAR', 'TUR', 'k = 2', 'published', 'calibrator'):
            self.assertIn(word, t)
        self.assertNotIn('\n', t)


if __name__ == '__main__':
    unittest.main()
