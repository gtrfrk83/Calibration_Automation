"""The 'Check an EMU' calculator model (emu_check_model.py): a nominal test point with units -> the uncertainty reported on the certificate (owner request 2026-10-27).
Run:  python -m unittest tests.test_emu_check_model"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import emu_check_model as m  # noqa: E402
import specmanager as sm  # noqa: E402
import uncertainty_budget as ub  # noqa: E402


class Calc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.std = sm.standard('5522A', cls.db)

    def test_units_do_not_change_the_answer(self):
        a = m.compute(self.std, m.Inputs('DCV', '250', 'mV'))
        b = m.compute(self.std, m.Inputs('DCV', '0.25', 'V'))
        c = m.compute(self.std, m.Inputs('DCV', '250000', 'µV'))
        self.assertEqual((a.cert_si, a.cert_text), (b.cert_si, b.cert_text))
        self.assertEqual(a.cert_si, c.cert_si)
        self.assertEqual(a.cert_text, '4.7 µV')

    def test_it_is_the_figure_the_reports_print(self):
        r = m.compute(self.std, m.Inputs('DCV', '250', 'mV'))
        b = ub.build('DCV', 0.25, 'V', standard=self.std)
        self.assertEqual(r.cert_si, b.reported)
        self.assertEqual(r.cert_text, ub.reported_text(b))
        self.assertGreaterEqual(r.cert_si, b.cmc)                          # never below the scope CMC
        self.assertGreaterEqual(r.cert_si, b.emu)

    def test_the_sheet_row_that_covers_the_point_is_named(self):
        r = m.compute(self.std, m.Inputs('DCV', '250', 'mV'))
        self.assertIn('Voltage, DC / 329.9999 mV', r.sheet_row)
        self.assertIn('Sheet row used', r.text)
        self.assertIn('Expanded uncertainty (k = 2)', r.text)

    def test_ac_needs_a_frequency_and_uses_it(self):
        self.assertEqual(m.compute(self.std, m.Inputs('ACV', '1', 'V')).error, 'Enter the frequency (an AC point needs one).')
        lo = m.compute(self.std, m.Inputs('ACV', '1', 'V', frequency='1', frequency_unit='kHz'))
        hi = m.compute(self.std, m.Inputs('ACV', '1', 'V', frequency='50', frequency_unit='kHz'))
        self.assertTrue(lo.cert_text and hi.cert_text)
        self.assertEqual(lo.cert_si, m.compute(self.std, m.Inputs('ACV', '1', 'V', frequency='1000', frequency_unit='Hz')).cert_si)
        self.assertNotEqual(lo.sheet_row, '')

    def test_resolution_and_type_a_are_added_when_given(self):
        base = m.compute(self.std, m.Inputs('DCV', '250', 'mV')).budget
        more = m.compute(self.std, m.Inputs('DCV', '250', 'mV', type_a='5', type_a_unit='µV')).budget
        self.assertGreater(more.emu, base.emu)
        self.assertIn('Type A', [c.name for c in more.components])

    def test_bad_input_is_explained_plainly(self):
        self.assertEqual(m.compute(self.std, m.Inputs('DCV', '', 'mV')).error, 'Enter the nominal test point.')
        self.assertIn('must be a number', m.compute(self.std, m.Inputs('DCV', 'abc', 'mV')).error)
        self.assertIn('not supported', m.compute(self.std, m.Inputs('POWAC', '1', 'W')).error)

    def test_an_uncertainty_already_reported_is_audited(self):
        ok = m.compute(self.std, m.Inputs('DCV', '250', 'mV', reported='10', reported_unit='µV'))
        low = m.compute(self.std, m.Inputs('DCV', '250', 'mV', reported='1', reported_unit='µV'))
        self.assertTrue(ok.audit.startswith(ub.OK)); self.assertFalse(low.audit.startswith(ub.OK))
        self.assertEqual(ok.cert_text, low.cert_text)                      # the figure to report does not depend on what was reported

    def test_every_unit_family_has_the_base_unit_first_or_a_sensible_default(self):
        for kind in m.KINDS:
            names = [n for n, _f in m.unit_choices(kind)]
            self.assertTrue(names)
            self.assertEqual(len(names), len(set(names)))
        self.assertEqual(m.default_unit('DCV', 0.12), 'mV')
        self.assertEqual(m.default_unit('DCV', 12), 'V')
        self.assertEqual(m.default_unit('OHM', 12000), 'kΩ')
        self.assertEqual(m.default_unit('FREQ', 5e6), 'MHz')

    def test_prefill_from_a_table_row(self):
        rows = [r for r in sm.rows_of(self.std.id, path=self.db) if r['kind'] == 'ACV' and r['amp_hi'] and r['freq_lo']]
        pre = m.prefill_from_row(rows[0])
        self.assertEqual(pre['kind'], 'ACV')
        self.assertTrue(pre['nominal'] and pre['frequency'])
        r = m.compute(self.std, m.Inputs(pre['kind'], pre['nominal'], pre['nominal_unit'], frequency=pre['frequency'], frequency_unit=pre['frequency_unit']))
        self.assertFalse(r.error)

    def test_relative_text(self):
        self.assertEqual(m.relative_text(3.24e-3, 1), '0.32 % of nominal')
        self.assertEqual(m.relative_text(3.2e-6, 0.25), '12.8 ppm of nominal')


if __name__ == '__main__':
    unittest.main()
