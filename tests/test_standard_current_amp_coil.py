"""Transconductance amplifier/coil sheet (specs/standards/a2la_current_amp_coil_standard.json, written by specs/build_current_amp_coil_standard.py): the lab's A2LA CMC for
AC current (20.5 to 3000) A, scope 1888.03 rev. 07/07/2026, printed p. 30 of 47.   Run:  python -m unittest tests.test_standard_current_amp_coil"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_current_amp_coil_standard as bc  # noqa: E402
import specmanager as sm  # noqa: E402
import specmanager_view as view  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'a2la_current_amp_coil_standard.json')
MODEL = 'A2LA-CURRENT-AMP-COIL'


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s = sm.standard(MODEL, cls.db)
        with open(JSON_PATH, encoding='utf-8') as fh:
            cls.data = json.load(fh)

    def test_two_rows_as_read_from_the_page(self):
        self.assertEqual(len(self.s.rows), 2)
        self.assertFalse([p for p in self.data['problems'] if p['level'] == 'error'])
        self.assertFalse([p for p in sm.validate_data(self.data) if p['level'] == 'error'])
        got = [(r['kind'], r['amp_lo'], r['amp_hi'], r['freq_lo'], r['freq_hi'], r['specs'][0]['rel'], r['specs'][0]['abs'], r['page']) for r in self.s.rows]
        self.assertEqual(got, [('ACI', 20.5, 3000.0, 16.0, 850.0, 0.007, 0.84, 30), ('ACI', 20.5, 3000.0, 850.0, 6000.0, 0.008, 0.84, 30)])
        self.assertEqual([r['label'] for r in self.s.rows], ['(20.5 to 3000) A, (16 to 850) Hz', '(20.5 to 3000) A, (0.85 to 6) kHz'])
        self.assertEqual([r['specs'][0]['raw'] for r in self.s.rows], ['[1 yr] Accuracy: +/-(0.7 % I.V. + 0.84 A)', '[1 yr] Accuracy: +/-(0.8 % I.V. + 0.84 A)'])
        for r in self.s.rows:
            self.assertEqual((r['direction'], r['unit'], r['variant']), ('output', 'A', 'Transconductance amplifier/coil'))
            self.assertEqual([s['period'] for s in r['specs']], ['1 yr'])
            self.assertEqual((r['specs'][0]['fs_rel'], r['specs'][0]['fs_value']), (0.0, 0.0))

    def test_confidence_and_status(self):
        self.assertEqual(self.s.info['confidence_pct'], 95.0)
        self.assertEqual(self.s.divisor()[0], 2.0)
        self.assertTrue(bc.VERIFIED_AGAINST_IMAGE)
        self.assertIn('RENDERED PAGE IMAGE', self.data['notes']['2'])
        self.assertFalse([p for p in self.data['problems'] if 'UNVERIFIED' in p['what']])
        self.assertEqual(self.data['standard']['description'], 'Transconductance amplifier/coil (A2LA scope, AC current)')

    def test_builder_reproduces_the_shipped_sheet(self):
        fresh = bc.build()
        for d in (fresh, self.data):
            d['standard'].pop('built')
        self.assertEqual(fresh, self.data)

    def test_lookup(self):
        self.assertAlmostEqual(self.s.lookup('ACI', 1000.0, frequency=50.0).limit, 0.007 * 1000 + 0.84, 9)
        self.assertAlmostEqual(self.s.lookup('ACI', 1000.0, frequency=2000.0).limit, 0.008 * 1000 + 0.84, 9)
        self.assertAlmostEqual(self.s.lookup('ACI', 1000.0, frequency=850.0).limit, 0.008 * 1000 + 0.84, 9)      # border: the larger limit
        self.assertIsNone(self.s.lookup('ACI', 1000.0, frequency=15.0))
        self.assertIsNone(self.s.lookup('ACI', 1000.0, frequency=6001.0))
        self.assertIsNone(self.s.lookup('ACI', 1000.0))
        self.assertIsNone(self.s.lookup('ACI', 20.0, frequency=50.0))
        self.assertIsNone(self.s.lookup('ACI', 3000.1, frequency=50.0))
        self.assertIsNone(self.s.lookup('DCI', 1000.0))
        b = ub.build('ACI', 1000.0, 'A', standard=self.s, frequency=50.0, scope=None)
        self.assertAlmostEqual(b.emu, 7.84, 9)

    def test_other_names_not_captured(self):
        self.assertEqual(sm.standard('Fluke 5522A', self.db).model, '5522A')
        self.assertEqual(sm.standard('A2LA-5500A-COIL', self.db).model, 'A2LA-5500A-COIL')
        self.assertEqual(sm.standard(MODEL, self.db).model, MODEL)

    def test_view(self):
        row = next(x for x in sm.standards(self.db) if x['model'] == MODEL)
        rows = sm.rows_of(row['id'], path=self.db)
        self.assertEqual([(c[0], c[2]) for c in view.kind_chips(rows)], [('', 2), ('ACI', 2)])
        self.assertEqual(view.freq_text(rows[0]), '16.0 Hz to 850 Hz')
        self.assertEqual(view.spec_cell(rows[0], '1 yr')[0], '±(0.7 % + 840 mA)')
        self.assertEqual(view.spec_cell(rows[1], '1 yr')[0], '±(0.8 % + 840 mA)')
        self.assertEqual(len(view.group_rows(rows)), 1)


if __name__ == '__main__':
    unittest.main()
