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
        self.assertIn('not supported', m.compute(self.std, m.Inputs('FLAT', '1', 'V')).error)
        self.assertIn('no Inductance specification', m.compute(self.std, m.Inputs('IND', '1', 'mH')).error)

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


class FullyFledged(unittest.TestCase):
    """Owner request 2026-10-29: every choice the sheet has (sensor, direction, sheet function, period, °F) and the selected spec line fills the window."""

    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.std = sm.standard('5522A', cls.db)

    def calc(self, *a, std=None, **k):
        return m.compute(std or self.std, m.Inputs(*a, **k))

    def test_temperature_sensor_choice(self):
        o = m.options(self.std)['TEMP']
        keys = [c.value for c in o.functions['output']]
        for want in ('B', 'E', 'J', 'K', 'N', 'R', 'S', 'T', 'Pt385-100', 'Pt3926-100', 'Cu427-10', 'PtNi385-120'):
            self.assertIn(want, keys)
        self.assertEqual(o.directions, ['output', 'input'])
        k = self.calc('TEMP', '100', '°C')
        j = self.calc('TEMP', '100', '°C', function='J')
        rtd = self.calc('TEMP', '100', '°C', function='Pt385-100')
        self.assertIn('Type K Output', k.sheet_row)
        self.assertIn('Type J Output', j.sheet_row)
        self.assertIn('Pt 385, 100 Ohm', rtd.sheet_row)
        self.assertNotIn('1000 Ohm', rtd.sheet_row)
        b = ub.build('TEMP', 100.0, 'degC', standard=self.std, tc='J', variant='Type J Output')
        self.assertEqual(j.cert_si, b.reported)                    # the same figure an engine on Type J would report
        self.assertIn('Type J thermocouple', j.text)

    def test_temperature_in_fahrenheit_and_kelvin(self):
        c = self.calc('TEMP', '100', '°C', function='J')
        f = self.calc('TEMP', '212', '°F', function='J')
        kel = self.calc('TEMP', '373.15', 'K', function='J')
        self.assertEqual(c.cert_si, f.cert_si)
        self.assertEqual(c.cert_si, kel.cert_si)
        self.assertIn('°F)', f.cert_text)
        self.assertIn('212 °F = 100 °C', f.text)
        typed = self.calc('TEMP', '212', '°F', function='J', type_a='0.18', type_a_unit='°F')     # a difference: 0.18 °F = 0.1 °C
        ref = self.calc('TEMP', '100', '°C', function='J', type_a='0.1', type_a_unit='°C')
        self.assertAlmostEqual(typed.budget.emu, ref.budget.emu, places=9)

    def test_thermocouple_measure_direction(self):
        r = self.calc('TEMP', '100', '°C', function='K', direction='input')
        self.assertIn('Type K Input', r.sheet_row)
        self.assertIn('measures the point', r.text)

    def test_period_choice(self):
        p = m.options(self.std)['ACV'].periods[('output', '')]
        self.assertIn('90 day', p)
        self.assertIn('1 yr', p)
        a = self.calc('ACV', '1', 'V', frequency='1', frequency_unit='kHz', period='90 day')
        b = self.calc('ACV', '1', 'V', frequency='1', frequency_unit='kHz')
        self.assertIn('[90 day]', a.sheet_row)
        self.assertIn('[1 yr]', b.sheet_row)
        self.assertLessEqual(a.budget.emu, b.budget.emu)
        self.assertIn('no 2 yr specification', self.calc('ACV', '1', 'V', frequency='1', frequency_unit='kHz', period='2 yr').error)

    def test_a_measuring_standard_works(self):
        for model, args, kw in (('3458A', ('DCV', '1', 'V'), {}), ('5790B', ('ACV', '1', 'V'), dict(frequency='1', frequency_unit='kHz')),
                                ('34461A', ('OHM', '1', 'kΩ'), {})):
            std = sm.standard(model, self.db)
            self.assertEqual(m.options(std)[args[0]].directions, ['input'], model)
            r = self.calc(*args, std=std, **kw)
            self.assertFalse(r.error, (model, r.error))
            self.assertIn('measures the point', r.text)

    def test_a_chosen_sheet_function_is_used(self):
        fns = [c.value for c in m.options(self.std)['ACV'].functions['output']]
        self.assertIn('Voltage, AC [Sinewave]', fns)
        r = self.calc('ACV', '1', 'V', frequency='1', frequency_unit='kHz', function='Voltage, AC [Sinewave]')
        self.assertTrue(r.sheet_row.startswith('Voltage, AC [Sinewave] /'))
        self.assertIn('no function', self.calc('ACV', '1', 'V', frequency='1', frequency_unit='kHz', function='Voltage, AC [Nope]').error)

    def test_the_other_functions_of_the_sheet(self):
        self.assertTrue(self.calc('POWAC', '100', 'W', frequency='60').cert_text)
        self.assertTrue(self.calc('POWDC', '10', 'W').cert_text)
        self.assertTrue(self.calc('PHASE', '45', '°', frequency='60').cert_text.endswith('°'))
        self.assertTrue(self.calc('COND', '10', 'nS').cert_text)
        self.assertTrue(self.calc('TIME', '1', 'ms').cert_text)
        self.assertTrue(self.calc('IND', '10', 'mH', frequency='1', frequency_unit='kHz', std=sm.standard('5560A', self.db)).cert_text)
        self.assertTrue(self.calc('LUX', '100', 'lux', std=sm.standard('T-10A', self.db)).cert_text.endswith('lux'))
        rf = self.calc('RFLEVEL', '-10', 'dBm', frequency='100', frequency_unit='MHz', std=sm.standard('96270A', self.db))
        self.assertTrue(rf.cert_text.endswith('dB'), rf.error)
        self.assertIn('Enter the frequency', self.calc('RFLEVEL', '-10', 'dBm', std=sm.standard('96270A', self.db)).error)

    def test_the_selected_spec_line_fills_everything(self):
        rows = sm.rows_of(self.std.id, path=self.db)
        tc = next(r for r in rows if r['kind'] == 'TEMP' and 'Type J Input' in r['function'] and r['unit'] == 'degC')
        pre = m.prefill_from_row(tc)
        self.assertEqual((pre['kind'], pre['direction'], pre['function']), ('TEMP', 'input', 'J'))
        r = m.compute(self.std, m.Inputs(pre['kind'], pre['nominal'], pre['nominal_unit'], direction=pre['direction'], function=pre['function']))
        self.assertIn('Type J Input', r.sheet_row)
        self.assertIn(tc['label'], r.sheet_row)
        rtd = next(r for r in rows if r['kind'] == 'TEMP' and 'Pt 385, 200 Ohm' in r['function'])
        self.assertEqual(m.prefill_from_row(rtd)['function'], 'Pt385-200')
        fahr = next((r for r in rows if r['kind'] == 'TEMP' and r['unit'] == 'degF'), None)
        if fahr is not None:
            self.assertEqual(m.prefill_from_row(fahr)['nominal_unit'], '°F')
        sine = next(r for r in rows if r['function'] == 'Voltage, AC [Sinewave]' and r['freq_lo'])
        pre = m.prefill_from_row(sine)
        self.assertEqual(pre['function'], 'Voltage, AC [Sinewave]')
        r = m.compute(self.std, m.Inputs(pre['kind'], pre['nominal'], pre['nominal_unit'], frequency=pre['frequency'], frequency_unit=pre['frequency_unit'],
                                          direction=pre['direction'], function=pre['function']))
        self.assertIn(sine['label'], r.sheet_row)
        flat = next(r for r in rows if r['kind'] == 'FLAT')
        self.assertEqual(m.prefill_from_row(flat)['kind'], '')
        self.assertIn('flatness', m.prefill_from_row(flat)['why'])

    def test_every_offered_function_of_every_sheet_computes_at_its_first_row(self):
        """Nothing offered in a drop-down ends in an exception: each sheet function at the top of its first range gives a figure or a plain reason."""
        for s in sm.standards(self.db):
            std = sm.standard(s['id'], self.db)
            for kind, ko in m.options(std).items():
                for d in ko.directions:
                    for c in ko.functions[d][:6]:
                        row = next(r for r in m._rows_for(std, kind, d, c.value))
                        pre = m.prefill_from_row(row)
                        r = m.compute(std, m.Inputs(kind, pre['nominal'] or '1', pre['nominal_unit'], frequency=pre['frequency'], frequency_unit=pre['frequency_unit'],
                                                    direction=d, function=c.value))
                        self.assertTrue(r.cert_text or r.error, (s['model'], kind, d, c.value))


if __name__ == '__main__':
    unittest.main()
