"""Run:  python -m unittest tests.test_specmanager   (from the repository folder; tkinter is stubbed so it also runs headless)"""
import os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import tkinter  # noqa: F401
except ImportError:
    for m in ('tkinter', 'tkinter.ttk', 'tkinter.font', 'tkinter.messagebox', 'tkinter.filedialog', 'tkinter.simpledialog'):
        sys.modules[m] = mock.MagicMock()

import specmanager as sm
import uncertainty
import uncertainty_budget as ub

DB = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sm.seed(path=DB)
        cls.a = sm.standard('5522A', DB)
        cls.b = sm.standard('5560A', DB)
        cls.sc = uncertainty.load()

    def test_divisor(self):
        self.assertEqual(self.a.divisor()[0], 2.0)
        self.assertEqual(self.b.divisor()[0], 1.96)

    def test_wizard_example(self):                       # 100 mV on the 5522A: 1.5 uV standard, 28.9 nV resolution, EMU 3 uV
        b = ub.build('DCV', 0.1, 'V', standard=self.a, scope=self.sc)
        self.assertAlmostEqual(b.components[0].u, 1.5e-6, 12)
        self.assertAlmostEqual(b.components[1].u, 28.87e-9, 11)
        self.assertAlmostEqual(b.emu, 3.0e-6, 8)

    def test_reported_never_below_cmc_or_budget(self):
        for kind, v, f in [('DCV', .1, None), ('DCV', 10, None), ('ACV', 1, 1e3), ('DCI', .01, None), ('OHM', 100, None)]:
            for st in (self.a, self.b):
                b = ub.build(kind, v, '', standard=st, frequency=f, scope=self.sc)
                self.assertGreaterEqual(b.reported, b.cmc)
                self.assertGreaterEqual(b.reported, (b.emu or 0))

    def test_audit(self):
        b = ub.build('DCV', 0.1, 'V', standard=self.a, scope=self.sc)
        self.assertEqual(ub.audit(1e-6, b)[0], ub.UNDER_CMC)
        self.assertEqual(ub.audit(2.5e-6, b)[0], ub.UNDER_BUDGET)
        self.assertEqual(ub.audit(b.reported, b)[0], ub.OK)
        self.assertEqual(ub.audit(1.0, ub.build('DCV', 5e6, 'V', standard=self.a, scope=self.sc))[0], ub.NOT_IN_SCOPE)

    def test_nested_ranges_use_tightest(self):
        self.assertEqual(self.b.lookup('DCV', 1.0).row['label'], '1.2V')

    def test_ceil_sig(self):
        self.assertEqual(ub.ceil_sig(3.0006e-6), 3.1e-6)
        self.assertEqual(ub.ceil_sig(3.0e-6), 3.0e-6)

    def test_edit_logged_and_roundtrip(self):
        sm.set_standard_field(self.a.id, 'divisor', 1.96, who='t', reason='test', path=DB)
        self.assertEqual(sm.standard('5522A', DB).divisor()[0], 1.96)
        self.assertTrue(sm.log_for(self.a.id, path=DB))
        sm.set_standard_field(self.a.id, 'divisor', None, path=DB)
        self.assertTrue(sm.import_data(sm.export_data(self.a.id, path=DB), path=DB))

    def test_bad_db_never_raises(self):
        self.assertEqual(sm.standards(path='/nonexistent/x.sqlite3'), [])
        self.assertIsNone(sm.standard('5522A', '/nonexistent/x.sqlite3'))


if __name__ == '__main__':
    unittest.main()
