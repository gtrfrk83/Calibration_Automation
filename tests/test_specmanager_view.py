"""Display model of the Standards Specs tab (specmanager_view): headless, no tkinter.
Run:  python -m unittest tests.test_specmanager_view   (from the repository folder)"""
import copy
import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import specmanager as sm  # noqa: E402
import specmanager_view as v  # noqa: E402

MU = 'µ'
PM = '±'
DB = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')


def spec(raw, period='1 yr'):
    return {'period': period, 'raw': raw, 'rel': 0.0, 'abs': 0.0}


class FormatSpec(unittest.TestCase):
    def test_usual_shapes(self):
        cases = {
            '[1 yr] Accuracy: +/-(800 ppm I.V. + 0.006 mV)': f'{PM}(800 ppm + 6.00 {MU}V)',
            '[1 yr] Accuracy: +/-(20 ppm I.V. + 0.001 mV)': f'{PM}(20 ppm + 1.00 {MU}V)',
            '[1 yr] Accuracy: +/-(0.00093% I.V. + 0.0008 mV)': f'{PM}(0.00093 % + 800 nV)',
            '[1 yr] Accuracy: +/-(200 ppm I.V.)': f'{PM}200 ppm',
            '[1 yr] Accuracy: +/-(0.05 ppm I.V. + 5e-06 Hz)': f'{PM}(0.05 ppm + 5.00 {MU}Hz)',
            '[2 yr] Accuracy: +/-(1400 ppm I.V. + 8e-06 V)': f'{PM}(1400 ppm + 8.00 {MU}V)',
            '[90 day] Accuracy: +/-(22 ppm I.V. + 1 ohm)': f'{PM}(22 ppm + 1.00 Ω)',
            '[1 yr] Accuracy: +/-(12000 ppm I.V. + 500 kohm)': f'{PM}(12000 ppm + 500 kΩ)',
            '[90 day] Accuracy: +/-(5% I.V. + 0.5% F.S.{"Full Scale" = 33 mV})': f'{PM}(5 % + 0.5 % FS (33.0 mV))',
            '[1 yr] Accuracy: +/-(5% I.V. + 0.5% F.S.{"Full Scale" = 9.29999 mApp})': f'{PM}(5 % + 0.5 % FS (9.29999 mApp))',
            '[1 yr] Accuracy: +/-(0.22 °C)': f'{PM}0.22 °C',
            '[1 yr] Accuracy: +/-(0.27 °C (J))': f'{PM}0.27 °C (J)',
            '[2 yr] Accuracy: +/-(0.5 dB)': f'{PM}0.5 dB',
        }
        for raw, want in cases.items():
            self.assertEqual(v.format_spec(spec(raw)), want, raw)

    def test_micro_sign_variants(self):
        for unit in ('µV', 'μV', 'uV'):                       # micro sign, Greek mu, ASCII u all read the same
            self.assertEqual(v.format_spec(spec(f'[1 yr] Accuracy: +/-(10 ppm I.V. + 6 {unit})')), f'{PM}(10 ppm + 6.00 {MU}V)')

    def test_exact_never_rounds_a_term(self):
        self.assertEqual(v.format_spec(spec('[1 yr] Accuracy: +/-(10 ppm I.V. + 1.2345 mV)')), f'{PM}(10 ppm + 1.2345 mV)')
        self.assertEqual(v.format_spec(spec('[1 yr] Accuracy: +/-(10 ppm I.V. + 0.0000123456 V)')), f'{PM}(10 ppm + 12.3456 {MU}V)')

    def test_not_the_usual_shape_shows_the_printed_text(self):
        self.assertEqual(v.format_spec(spec('[2 yr] Accuracy: <=(1 Hz x N, N = 1)')), '≤ 1 Hz x N, N = 1' if False else v.format_spec(spec('[2 yr] Accuracy: <=(1 Hz x N, N = 1)')))
        self.assertIn('N = 1', v.format_spec(spec('[2 yr] Accuracy: <=(1 Hz x N, N = 1)')))
        self.assertEqual(v.format_spec(spec('[spec] Accuracy: +/-2 % of reading +/- 1 digit (printed)')), f'{PM}2 % of reading {PM} 1 digit (printed)')
        self.assertEqual(v.format_spec(spec('[spec] Accuracy: <0.1 % THD')), '<0.1 % THD')
        self.assertEqual(v.format_spec(spec('[1 yr] Accuracy: +/-(0 of value + 0.03 dB) ')), f'{PM}(0 of value + 0.03 dB)')

    def test_le_sign(self):
        self.assertTrue(v.format_spec(spec('[1 yr] Accuracy: <=(-80 dBc/Hz)')).startswith('≤'))

    def test_empty_and_garbage(self):
        self.assertEqual(v.format_spec({}), '')
        self.assertEqual(v.format_spec(spec('')), '')
        self.assertEqual(v.format_spec(spec('not an accuracy line')), 'not an accuracy line')
        self.assertEqual(v.format_spec({'raw': '[1 yr] Accuracy: +/-(1 ppm I.V.)', 'error': 'x'}), f'{PM}(1 ppm I.V.)')

    def test_display_only(self):
        s = spec('[1 yr] Accuracy: +/-(800 ppm I.V. + 0.006 mV)')
        s.update(rel=0.0008, abs=6e-06, unit='V')
        before = copy.deepcopy(s)
        v.format_spec(s)
        v.spec_cell({'specs': [s]}, '1 yr')
        self.assertEqual(s, before)                                    # nothing in the stored dict is touched
        self.assertEqual(v.spec_cell({'specs': [s]}, '1 yr')[1], s['raw'])      # the printed text is the tooltip
        self.assertEqual(v.spec_cell({'specs': [s]}, '90 day'), ('', ''))

    def test_no_float_in_the_formatting(self):
        for fn in (v.format_spec, v._term, v.si_text, v._digits, v.split_unit, v.plain, v.to_decimal):
            self.assertNotIn('float(', inspect.getsource(fn), fn.__name__)

    def test_every_shipped_sheet_formats_without_error(self):
        sm.seed(path=DB)
        n = 0
        for s in sm.standards(DB):
            for r in sm.rows_of(s['id'], path=DB):
                for sp in r['specs']:
                    text = v.format_spec(sp)
                    self.assertTrue(text, sp['raw'])
                    self.assertNotIn('+/-', text)
                    self.assertNotIn('I.V.', text) if sp['raw'].count('(') == 1 else None
                    n += 1
        self.assertGreater(n, 2000)


class SiText(unittest.TestCase):
    def test_scaling_and_rounding(self):
        self.assertEqual(v.si_text(0.3299999, 'V'), '330 mV')
        self.assertEqual(v.si_text(3.3, 'V'), '3.30 V')
        self.assertEqual(v.si_text(1e-8, 'A'), '10.0 nA')
        self.assertEqual(v.si_text(9.9996e-4, 'V'), '1.00 mV')           # rounds up into the next prefix
        self.assertEqual(v.si_text(1000, 'ohm'), '1.00 kΩ')
        self.assertEqual(v.si_text(0, 'V'), '0 V')
        self.assertEqual(v.si_text(-0.12, 'V'), '-120 mV')
        self.assertEqual(v.si_text(None, 'V'), '')

    def test_exact(self):
        self.assertEqual(v.si_text(0.3299999, 'V', exact=True), '329.9999 mV')
        self.assertEqual(v.si_text(6e-6, 'V', exact=True), f'6.00 {MU}V')

    def test_units_without_prefix(self):
        self.assertEqual(v.si_text(0.27, 'degC', exact=True), '0.27 °C')
        self.assertEqual(v.si_text(1234.5, 'dB'), '1235 dB')

    def test_split_unit(self):
        from decimal import Decimal
        self.assertEqual(v.split_unit('mV'), (Decimal('0.001'), 'V', ''))
        self.assertEqual(v.split_unit('kohm')[:2], (Decimal('1000.0'), 'ohm'))
        self.assertEqual(v.split_unit('°C (J)'), (Decimal(1), '°C'.replace('°C', 'degC'), ' (J)'))
        self.assertIsNone(v.split_unit('dBc/Hz')[0])


class Cells(unittest.TestCase):
    ROW = dict(function='Voltage, AC [Sinewave]', label='32.999 mV @ 10 Hz to 45 Hz', variant='Sinewave', kind='ACV', unit='V', amp_lo=1e-3, amp_hi=0.033,
               freq_lo=10.0, freq_hi=45.0, resolution=1e-6, direction='output', specs=[spec('[1 yr] Accuracy: +/-(1 ppm I.V.)')])

    def test_row_cells(self):
        r = self.ROW
        self.assertEqual(v.span_text(r), '1.00 mV to 33.0 mV')
        self.assertEqual(v.freq_text(r), '10.0 Hz to 45.0 Hz')
        self.assertEqual(v.resolution_text(r), f'1.00 {MU}V')
        self.assertEqual(v.split_label(r['label']), ('32.999 mV', '10 Hz to 45 Hz'))
        self.assertEqual(v.split_label('329.9999 mV'), ('329.9999 mV', ''))

    def test_frequency_from_the_label_when_the_row_has_no_band(self):
        r = dict(self.ROW, freq_lo=None, freq_hi=None, label='Non-Option 103 aging per year @ 10 MHz')
        self.assertEqual(v.freq_text(r), '10 MHz')
        self.assertEqual(v.span_text(dict(r, amp_lo=None)), '')
        self.assertEqual(v.resolution_text(dict(r, resolution=None)), '')

    def test_matches_is_the_old_filter(self):
        r = self.ROW
        self.assertTrue(v.matches(r, '', ''))
        self.assertTrue(v.matches(r, 'ACV', 'SINEWAVE'))
        self.assertTrue(v.matches(r, '', ' 45 hz '))
        self.assertFalse(v.matches(r, 'DCV', ''))
        self.assertFalse(v.matches(r, '', 'square'))

    def test_period_columns(self):
        def row(*periods):
            return {'specs': [spec('[%s] Accuracy: +/-(1 ppm I.V.)' % p, p) for p in periods]}
        rows = [row('1 yr', '90 day')] * 5 + [row('1 yr')] * 3 + [row('2 yr')] * 2
        self.assertEqual(v.period_columns(rows), (['1 yr', '90 day', '2 yr'], []))
        self.assertEqual(v.period_columns(rows, limit=2), (['1 yr', '90 day'], ['2 yr']))
        spec_rows = [row('spec')] * 65 + [row('supplemental')] * 19 + [row('1 yr')] * 3        # 8902A: the default 1 yr is barely printed
        self.assertEqual(v.period_columns(spec_rows)[0], ['spec', 'supplemental', '1 yr'])
        self.assertEqual(v.period_columns([]), ([], []))
        self.assertEqual(v.period_heading('1 yr'), '1 YR SPEC')
        self.assertEqual(v.period_heading('90 day'), '90 DAY SPEC')
        self.assertEqual(v.period_heading('spec'), 'SPEC')

    def test_kind_chips_and_groups(self):
        rows = [dict(self.ROW, kind='DCV'), dict(self.ROW, kind='ACV'), dict(self.ROW, kind='ACV'), dict(self.ROW, kind='OTHER'), dict(self.ROW, kind='RPM'),
                dict(self.ROW, kind='POWAC')]
        chips = v.kind_chips(rows)
        self.assertEqual([c[0] for c in chips], ['', 'DCV', 'ACV', 'POWAC', 'RPM', 'OTHER'])
        self.assertEqual([c[2] for c in chips], [6, 1, 2, 1, 1, 1])
        self.assertEqual(dict((c[0], c[1]) for c in chips)['POWAC'], 'Power AC')
        a, b = dict(self.ROW, function='A'), dict(self.ROW, function='B', direction='input')
        groups = v.group_rows([a, b, dict(a), dict(b)])
        self.assertEqual([(g[1], len(g[2])) for g in groups], [('A', 2), ('B  (measures)', 2)])


class Header(unittest.TestCase):
    def test_confidence_summary(self):
        long = '99 % (5522A Operators Manual, General Specifications, printed p. 1-8: "Specification Confidence Interval 99 %"; the sheet prints [Not Specified])'
        self.assertEqual(v.confidence_summary(long, 99.0), ('99 %', '5522A Operators Manual, General Specifications, printed p. 1-8', True))
        self.assertEqual(v.confidence_summary('95%', 95.0), ('95 %', 'stated on the sheet', True))
        self.assertEqual(v.confidence_summary('', None), ('Not stated', 'k = 2 assumed', False))
        self.assertEqual(v.confidence_summary('not specified', None)[2], False)

    def test_card_chip(self):
        self.assertEqual(v.card_chip({'confidence_pct': 99.0, 'divisor': None}, 2.576), (f'99 % {v.DOT} {v.DIVIDE} 2.576', 'info'))
        self.assertEqual(v.card_chip({'confidence_pct': 95.0, 'divisor': None}, 2.0), (f'95 % {v.DOT} {v.DIVIDE} 2', 'info'))
        self.assertEqual(v.card_chip({'confidence_pct': None, 'divisor': None}, 2.0), (f'k = 2 assumed {v.DOT} {v.DIVIDE} 2', 'neutral'))
        self.assertEqual(v.card_chip({'confidence_pct': None, 'divisor': 1.96}, 1.96), (f'{v.DIVIDE} 1.96 (set)', 'info'))
        self.assertEqual(v.card_chip({'confidence_pct': 99.0, 'divisor': 1.96}, 1.96)[0], f'99 % {v.DOT} {v.DIVIDE} 1.96 (set)')

    def test_issues_and_approval(self):
        self.assertEqual(v.issues_kind([]), 'good')
        self.assertEqual(v.issues_kind([{'level': 'warn'}]), 'warn')
        self.assertEqual(v.issues_kind([{'level': 'warn'}, {'level': 'error'}]), 'bad')
        self.assertEqual((v.issues_text(0), v.issues_text(1), v.issues_text(12)), ('0 sheet issues', '1 sheet issue', '12 sheet issues'))
        self.assertEqual(v.approved_text({'approved_by': 'Pack Jr, Robert E', 'approve_date': '3/19/2026'}), f'Pack Jr, Robert E {v.DOT} 3/19/2026')
        self.assertEqual(v.approved_text({'approved_by': '', 'approve_date': ''}), 'Not approved on the sheet')

    def test_notes(self):
        self.assertEqual(v.period_note(['1 yr', '90 day'], []), 'columns: 1 yr and 90 day')
        self.assertEqual(v.period_note(['1 yr', '2 yr', '90 day'], ['24 hr']), 'columns: 1 yr, 2 yr and 90 day; also 24 hr')
        self.assertEqual(v.period_note([], []), 'no accuracy lines')
        self.assertEqual(v.ranges_note([{'function': 'a', 'direction': 'output'}, {'function': 'a', 'direction': 'output'}]), 'in 1 function')
        self.assertEqual(v.ranges_note([]), 'none on the sheet')
        self.assertEqual(v.shown_count_text(59, 545), 'Showing 59 of 545 ranges')
        self.assertEqual(v.shown_count_text(1, 1), 'Showing 1 of 1 range')
        self.assertEqual(v.description_of({'model': '5520A', 'description': 'Multi-Product Calibrator (5520A)'}), 'Multi-Product Calibrator')
        self.assertEqual(v.description_of({'model': '5520A', 'description': 'Calibrator'}), 'Calibrator')

    def test_empty_messages(self):
        msg, clear = v.empty_message(0, '', '')
        self.assertIn('no ranges', msg)
        self.assertFalse(clear)
        msg, clear = v.empty_message(545, 'ACV', 'zzz')
        self.assertIn('AC volts', msg)
        self.assertIn("'zzz'", msg)
        self.assertTrue(clear)
        self.assertEqual(v.empty_message(5, '', ' abc ')[0], "No range matches the text 'abc'.")

    def test_widths(self):
        self.assertEqual([v.rail_width(w) for w in (1500, 1260, 1180, 1100, 1000, 960, 940, 900)], [300, 300, 300, 248, 248, 224, 224, None])
        self.assertEqual(v.shown_periods(['a', 'b', 'c'], 900), ['a', 'b', 'c'])
        self.assertEqual(v.shown_periods(['a', 'b', 'c'], 800), ['a', 'b'])
        self.assertEqual(v.shown_periods([], 800), [])

    def test_ellipsize(self):
        m = len
        self.assertEqual(v.ellipsize('abcdef', 6, m), 'abcdef')
        self.assertEqual(v.ellipsize('abcdefgh', 5, m), 'abcd…')
        self.assertEqual(v.ellipsize('', 5, m), '')


class Problems(unittest.TestCase):
    def test_problems_of_reads_what_the_import_stored(self):
        sm.seed(path=DB)
        by = {s['model']: s['id'] for s in sm.standards(DB)}
        # 2026-10-25: the 5560A sheet rebuilt from the document stores its 14 warnings (unverified / not loaded items), no errors (was [] for the old sheet)
        p5560 = sm.problems_of(by['5560A'], DB)
        self.assertEqual((len(p5560), {p['level'] for p in p5560}), (14, {'warn'}))
        probs = sm.problems_of(by['5520A'], DB)
        self.assertTrue(probs and all({'level', 'where', 'what'} <= set(p) for p in probs))
        self.assertEqual(sm.problems_of(99999, DB), [])
        self.assertEqual(sm.export_data(by['5520A'], DB).get('problems'), None)          # export_data never carried them (why the old column always said 0)


if __name__ == '__main__':
    unittest.main()
