"""Coil standard sheet (specs/standards/a2la_5500a_coil_standard.json, written by specs/build_coil_standard.py): the laboratory's own A2LA CMC lines for the Fluke 5500A/COIL
(scope 1888.03 rev. 07/07/2026, section V: printed p. 9 of 47 DC Current - Generate, Transconductance amplifier/coil; printed p. 30 of 47 AC Current - Generate (cont),
Clamp-On Only, Multifunction calibrator/coil).

Run:  python -m unittest tests.test_standard_coil
"""
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'specs'))

import build_coil_standard as bc  # noqa: E402
import specmanager as sm  # noqa: E402
import specmanager_view as view  # noqa: E402
import tartur  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

JSON_PATH = os.path.join(HERE, 'specs', 'standards', 'a2la_5500a_coil_standard.json')
MODEL = 'A2LA-5500A-COIL'
# (kind, amp_lo, amp_hi, freq_lo, freq_hi, printed CMC, rel, abs in A), exactly as read from the rendered pages
SCOPE = [('DCI', 2.0, 20.0, None, None, '90 µA/A + 0.1 mA', 9e-05, 1e-04),
         ('DCI', 20.0, 120.0, None, None, '80 µA/A + 8 mA', 8e-05, 0.008),
         ('DCI', 120.0, 3000.0, None, None, '0.8 % + 0.08 A', 0.008, 0.08),
         ('ACI', 20.5, 1025.0, 45.0, 65.0, '0.8 %', 0.008, 0.0),
         ('ACI', 20.5, 1025.0, 65.0, 440.0, '0.99 %', 0.0099, 0.0)]


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s = sm.standard(MODEL, cls.db)
        with open(JSON_PATH, encoding='utf-8') as fh:
            cls.data = json.load(fh)

    def test_sheet_parses_and_has_the_five_scope_lines(self):
        self.assertIsNotNone(self.s)
        self.assertEqual(len(self.s.rows), 5)
        self.assertEqual(len(self.data['functions']), 2)
        self.assertFalse([p for p in self.data['problems'] if p['level'] == 'error'])
        self.assertFalse([p for p in sm.validate_data(self.data) if p['level'] == 'error'])
        got = [(r['kind'], r['amp_lo'], r['amp_hi'], r['freq_lo'], r['freq_hi']) for r in self.s.rows]
        self.assertEqual(got, [(k, lo, hi, flo, fhi) for k, lo, hi, flo, fhi, *_ in SCOPE])

    def test_ranges_units_direction_and_period(self):
        for r in self.s.rows:
            with self.subTest(label=r['label']):
                self.assertEqual(r['unit'], 'A')                                  # amperes as printed; nothing scaled or converted
                self.assertEqual(r['direction'], 'output')
                self.assertEqual([s['period'] for s in r['specs']], ['1 yr'])    # a CMC has no 90 day column
                self.assertEqual(r['page'], 9 if r['kind'] == 'DCI' else 30)      # printed page numbers of the scope
        self.assertEqual([r['label'] for r in self.s.rows[:3]], ['(2 to 20) A', '(20 to 120) A', '(120 to 3000) A'])   # printed range text

    def test_terms_stored_exactly_ppm_percent_and_fixed(self):
        for r, (_k, _lo, _hi, _fl, _fh, printed, rel, fixed) in zip(self.s.rows, SCOPE):
            sp = r['specs'][0]
            with self.subTest(printed=printed):
                self.assertEqual(sp['rel'], rel)                                  # the nearest float to the printed figure (Decimal, not binary multiplication)
                self.assertEqual(sp['abs'], fixed)
                self.assertEqual((sp['fs_rel'], sp['fs_value']), (0.0, 0.0))
        self.assertEqual(self.s.rows[0]['specs'][0]['raw'], '[1 yr] Accuracy: +/-(90 ppm I.V. + 0.1 mA)')      # 90 uA/A written as 90 ppm
        self.assertEqual(self.s.rows[2]['specs'][0]['raw'], '[1 yr] Accuracy: +/-(0.8 % I.V. + 0.08 A)')
        self.assertEqual(self.s.rows[4]['specs'][0]['raw'], '[1 yr] Accuracy: +/-(0.99 % I.V.)')
        for printed, text in (('90', '9e-05'), ('80', '8e-05')):
            self.assertEqual(float(Decimal(printed) / Decimal(1_000_000)), float(text))        # 90 ppm = 9e-05 exactly the nearest float (80 * 1e-6 in binary is 8.999999999999999e-05)
        self.assertNotEqual(90 * 1e-6, 9e-05)
        self.assertNotEqual(80 * 1e-6, 8e-05)
        self.assertEqual(float(Decimal('0.1') * Decimal('0.001')), 1e-4)

    def test_coil_comments_and_clamp_on_only_qualifier(self):
        dc = [r for r in self.s.rows if r['kind'] == 'DCI']
        ac = [r for r in self.s.rows if r['kind'] == 'ACI']
        self.assertEqual({r['variant'] for r in dc}, {'Transconductance amplifier/coil'})
        self.assertEqual({r['variant'] for r in ac}, {'Clamp-On Only, Multifunction calibrator/coil'})
        self.assertTrue(all('Clamp-On Only' in r['function'] for r in ac))
        self.assertFalse(any('Clamp-On' in r['function'] for r in dc))
        self.assertTrue(all(r['freq_lo'] is None for r in dc))                    # DC rows have no frequency
        # the explicit variant selects the clamp-on rows
        self.assertEqual(self.s.lookup('ACI', 500.0, frequency=50.0, variant='Clamp-On Only').row['freq_hi'], 65.0)
        self.assertIsNone(self.s.lookup('ACI', 500.0, frequency=50.0, variant='Transconductance'))

    def test_confidence_95_divisor_2_and_wording(self):
        self.assertEqual(self.s.info['confidence_pct'], 95.0)
        d, why = self.s.divisor()
        self.assertEqual(d, 2.0)
        self.assertIn('95', why)
        self.assertIn('approximately the 95 % level, usually k = 2', self.data['standard']['confidence_text'])
        self.assertIn('approximately the 95 % level', self.data['notes']['3'])
        self.assertEqual(self.s.period, '1 yr')

    def test_verification_status_and_datasheet_facts_are_recorded(self):
        self.assertTrue(bc.VERIFIED_AGAINST_IMAGE)
        self.assertIn('RENDERED PAGE IMAGES', self.data['notes']['2'])
        self.assertFalse([p for p in self.data['problems'] if 'UNVERIFIED' in p['what']])
        self.assertEqual(self.data['standard']['revision'], '07/07/2026')
        self.assertIn('1888.03', self.data['standard']['reference'])
        n7 = self.data['notes']['7']
        for fact in ('number of turns 50', '11 A rms continuous', '20 A rms for 2 minutes', 'DC, 45-440 Hz', '2.19999 A', '2.99999 A', '2.54 cm'):
            self.assertIn(fact, n7)
        n8 = self.data['notes']['8']
        self.assertIn('0.25 % of effective output + 0.5 A', n8)
        self.assertIn('0.50 % of effective output + 0.5 A', n8)
        self.assertIn('NOT added', n8)

    def test_interaction_uncertainty_is_not_in_any_row(self):
        for r in self.s.rows:
            sp = r['specs'][0]
            self.assertNotIn(0.5, (sp['abs'], sp['fs_value']))
            self.assertEqual(sp['fs_rel'], 0.0)
            self.assertEqual(r['qualifiers'], [])
        self.assertAlmostEqual(self.s.lookup('ACI', 500.0, frequency=50.0).limit, 4.0, 9)    # 0.8 % of 500 A, no 0.25 % + 0.5 A added

    def test_listing_and_name_lookup(self):
        row = next(x for x in sm.standards(self.db) if x['model'] == MODEL)
        self.assertEqual(row['rows'], 5)
        self.assertEqual(row['description'], 'Fluke 5500A/COIL (A2LA scope)')
        self.assertEqual(sm.standard('Fluke 5522A', self.db).model, '5522A')          # the new model captures no other name
        self.assertEqual(sm.standard('Fluke 5520A', self.db).model, '5520A')
        self.assertEqual(sm.standard('A2LA-LIGHT', self.db).model, 'A2LA-LIGHT')

    def test_builder_reproduces_the_shipped_sheet(self):
        fresh = bc.build()
        for d in (fresh, self.data):
            d['standard'].pop('built')
        self.assertEqual(fresh, self.data)

    def test_lookup_dc_rows_and_borders(self):
        h = self.s.lookup('DCI', 100.0)
        self.assertAlmostEqual(h.limit, 80e-6 * 100.0 + 0.008, 12)
        self.assertEqual(h.row['label'], '(20 to 120) A')
        self.assertAlmostEqual(self.s.lookup('DCI', 10.0).limit, 90e-6 * 10.0 + 1e-4, 12)
        self.assertAlmostEqual(self.s.lookup('DCI', 1000.0).limit, 0.008 * 1000.0 + 0.08, 9)
        self.assertAlmostEqual(self.s.lookup('DCI', 20.0).limit, 80e-6 * 20.0 + 0.008, 12)   # border: the larger limit (the scope CMC rule)
        self.assertAlmostEqual(self.s.lookup('DCI', -100.0).limit, self.s.lookup('DCI', 100.0).limit, 12)
        self.assertIsNone(self.s.lookup('DCI', 1.0))                                        # below the first printed range: no extrapolation
        self.assertIsNone(self.s.lookup('DCI', 3000.1))
        self.assertIsNone(self.s.lookup('DCV', 100.0))

    def test_lookup_ac_clamp_on_rows_need_a_frequency_inside_a_band(self):
        self.assertAlmostEqual(self.s.lookup('ACI', 500.0, frequency=50.0).limit, 4.0, 9)
        self.assertAlmostEqual(self.s.lookup('ACI', 500.0, frequency=400.0).limit, 4.95, 9)
        self.assertAlmostEqual(self.s.lookup('ACI', 500.0, frequency=65.0).limit, 4.95, 9)  # on the border: the larger limit
        self.assertIsNone(self.s.lookup('ACI', 500.0, frequency=44.0))
        self.assertIsNone(self.s.lookup('ACI', 500.0, frequency=441.0))
        self.assertIsNone(self.s.lookup('ACI', 500.0))                                      # an AC point without a frequency is not covered
        self.assertIsNone(self.s.lookup('ACI', 20.0, frequency=50.0))                       # below 20.5 A
        self.assertIsNone(self.s.lookup('ACI', 1026.0, frequency=50.0))

    def test_budget_for_a_dc_point_is_the_cmc(self):
        b = ub.build('DCI', 100.0, 'A', standard=self.s, scope=None)
        self.assertAlmostEqual(b.hit.limit, 0.016, 12)
        self.assertAlmostEqual(b.components[0].u, 0.008, 12)                                  # CMC / 2
        self.assertAlmostEqual(b.emu, 0.016, 12)                                              # k = 2 gives back the expanded CMC
        b = ub.build('ACI', 500.0, 'A', standard=self.s, frequency=50.0, scope=None)
        self.assertAlmostEqual(b.emu, 4.0, 9)

    def test_tartur_with_this_standard_and_the_scope_coil_rows(self):
        # the lab CMC table (specs/a2la_1888_03_cmc.json) now carries the coil lines, so the ratios are computed with any standard
        r = tartur.compute({'kind': 'DCI', 'unit': 'A', 'nominal': 100.0}, 99.0, 101.0, standard=MODEL)
        self.assertAlmostEqual(r['tolerance'], 1.0, 12)
        self.assertAlmostEqual(r['accuracy'], 0.016, 9)
        self.assertAlmostEqual(r['tar'], 1.0 / 0.016, 6)
        self.assertEqual(r['reason'], '')
        r = tartur.compute({'kind': 'ACI', 'unit': 'A', 'nominal': 500.0, 'frequency': 50.0}, 495.0, 505.0, standard=MODEL)
        self.assertAlmostEqual(r['accuracy'], 4.0, 9)                      # TAR: the sheet's 0.8 % of 500 A
        self.assertAlmostEqual(r['tar'], 5.0 / 4.0, 6)
        self.assertAlmostEqual(r['uncertainty'], 4.0, 6)                    # reported: the coil's own line is the floor (0.8 % of 500 A); the amplifier / coil line (0.7 % + 0.84 A = 4.34 A) is other equipment
        self.assertAlmostEqual(r['tur'], 5.0 / 4.0, 6)
        lim, unit = tartur.standard_accuracy(MODEL, 'DCI', 100.0)
        self.assertAlmostEqual(lim, 0.016, 12)
        self.assertEqual(unit, 'A')
        # a calibrator has no specification row at 100 A: TAR blank, the TUR comes from the scope CMC
        for std in ('5522A', '5560A'):
            r = tartur.compute({'kind': 'DCI', 'unit': 'A', 'nominal': 100.0}, 99.0, 101.0, standard=std)
            self.assertIsNone(r['tar'], std)
            self.assertIsNotNone(r['tur'], std)

    def test_not_a_calibrator_picker_entry(self):
        # handheld_dmm imports tkinter (absent in some test environments): read its picker list as text.  The picker chooses the instrument that is COMMANDED; the coil is not.
        import re
        with open(os.path.join(HERE, 'handheld_dmm.py'), encoding='utf-8') as fh:
            text = fh.read()
        choices = re.search(r'^CAL_CHOICES = (.*)$', text, re.M).group(1)
        self.assertNotIn('COIL', choices.upper())
        self.assertNotIn('A2LA', choices.upper())

    def test_standards_specs_view_shows_the_sheet(self):
        row = next(x for x in sm.standards(self.db) if x['model'] == MODEL)
        rows = sm.rows_of(row['id'], path=self.db)
        chips = view.kind_chips(rows)
        self.assertEqual([(c[0], c[2]) for c in chips], [('', 5), ('DCI', 3), ('ACI', 2)])
        self.assertEqual(view.span_text(rows[0]), '2.00 A to 20.0 A')
        self.assertEqual(view.span_text(rows[1]), '20.0 A to 120 A')
        self.assertEqual(view.freq_text(rows[3]), '45.0 Hz to 65.0 Hz')
        self.assertEqual(view.spec_cell(rows[0], '1 yr')[0], '±(90 ppm + 100 µA)')
        self.assertEqual(view.spec_cell(rows[3], '1 yr')[0], '±0.8 %')
        self.assertEqual(view.spec_cell(rows[4], '1 yr')[0], '±0.99 %')
        self.assertEqual(len(view.group_rows(rows)), 2)
        self.assertTrue(view.matches(rows[3], '', 'clamp-on'))                              # 'Clamp-On Only' is searchable
        self.assertFalse(view.matches(rows[0], '', 'clamp-on'))


if __name__ == '__main__':
    unittest.main()
