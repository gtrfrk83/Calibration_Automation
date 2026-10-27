"""The Agilent 33250A standards sheet (80 MHz function / arbitrary waveform generator as a stimulus source).

The numbers below are a SECOND, hand-typed transcription of the manual's Chapter 8 'Specifications' (User's Guide 33250-90002 Edition 2, printed pp. 320-321 =
PDF pp. 321-322), read again from a 260 dpi render of those pages; they are deliberately NOT imported from the builder.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'specs'))
import specmanager as sm  # noqa: E402
import build_33250a_standard as b  # noqa: E402

SHEET = ROOT / 'specs' / 'standards' / 'agilent_33250a_standard.json'


def rows_of(data):
    return {f['name']: f['ranges'] for f in data['functions']}


class Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(SHEET.read_text(encoding='utf-8'))
        cls.rows = rows_of(cls.data)
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.std = sm.standard('33250A', cls.db)

    def one(self, fn, i=0):
        r = self.rows[fn][i]
        self.assertEqual(len(r['specs']), 1)
        self.assertEqual(r['specs'][0]['period'], '1 yr')
        return r, r['specs'][0]

    def test_builder_reproduces_the_shipped_sheet(self):
        self.assertEqual(b.build(), self.data)

    def test_no_sheet_check_errors(self):
        self.assertEqual([p for p in self.data['problems'] if p['level'] == 'error'], [])
        self.assertEqual([p for p in sm.validate_data(self.data) if p['level'] == 'error'], [])

    def test_functions_and_directions(self):
        self.assertEqual(set(self.rows), {
            'Frequency', 'Voltage, AC [Sinewave into 50 Ohm, Vpp]', 'Flatness [Sinewave relative to 1 kHz, 50 Ohm]',
            'Voltage, DC [Offset, DC Volts waveform, 50 Ohm]', 'Voltage, DC [Offset under a waveform, 50 Ohm]', 'Rise Time [Square wave into 50 Ohm]',
            'Time [Square wave Asymmetry]', 'Time [Square wave Jitter (rms), below 2 MHz]', 'Time [Square wave Jitter (rms), 2 MHz and above]',
            'Time [Pulse Jitter (rms)]', 'Time [Arb Jitter (rms)]', 'Sinewave Spectral Purity [Harmonic Distortion]',
            'Sinewave Spectral Purity [Total Harmonic Distortion]', 'Sinewave Spectral Purity [Spurious (non-harmonic)]'})
        self.assertEqual({f['direction'] for f in self.data['functions']}, {'output'})
        self.assertEqual(sum(len(v) for v in self.rows.values()), 27)

    def test_frequency_2_ppm_one_year(self):                     # printed p. 320: Accuracy (1 year): 2 ppm, 18 degC to 28 degC
        r, s = self.one('Frequency')
        self.assertEqual((r['kind'], r['amp_lo'], r['amp_hi'], r['unit']), ('FREQ', 1e-6, 80e6, 'Hz'))
        self.assertEqual((s['rel'], s['abs'], s['le']), (2e-6, 0.0, False))

    def test_amplitude_accuracy_at_1_khz_and_bands(self):        # printed p. 321: +/-1 % of setting +/-1 mVpp; flatness 1 % / 2 % / 5 %
        want = [((1000.0, 1000.0), 0.01), ((1e-6, 999.999999), 0.02), ((1000.000001, 10e6), 0.02), ((10e6, 50e6), 0.03), ((50e6, 80e6), 0.06)]
        for i, ((flo, fhi), rel) in enumerate(want):
            r, s = self.one('Voltage, AC [Sinewave into 50 Ohm, Vpp]', i)
            self.assertEqual((r['kind'], r['unit'], r['amp_lo'], r['amp_hi'], r['freq_lo'], r['freq_hi']), ('ACV', 'Vpp', 0.01, 10.0, flo, fhi))
            self.assertAlmostEqual(s['rel'], rel, 12)
            self.assertAlmostEqual(s['abs'], 0.001, 12)

    def test_flatness_as_printed(self):
        want = [((1e-6, 10e6), 0.01), ((10e6, 50e6), 0.02), ((50e6, 80e6), 0.05)]
        for i, ((flo, fhi), rel) in enumerate(want):
            r, s = self.one('Flatness [Sinewave relative to 1 kHz, 50 Ohm]', i)
            self.assertEqual((r['kind'], r['freq_lo'], r['freq_hi']), ('FLAT', flo, fhi))
            self.assertAlmostEqual(s['rel'], rel, 12)
            self.assertEqual(s['abs'], 0.0)
        self.assertIn('(0.1 dB)', self.rows['Flatness [Sinewave relative to 1 kHz, 50 Ohm]'][0]['label'])

    def test_offset(self):                                       # printed p. 321: +/-5 V; 1 % of setting + 2 mV + 0.5 % of amplitude
        r, s = self.one('Voltage, DC [Offset, DC Volts waveform, 50 Ohm]')
        self.assertEqual((r['kind'], r['amp_lo'], r['amp_hi'], r['unit']), ('DCV', -5.0, 5.0, 'V'))
        self.assertEqual((s['rel'], s['abs'], s['fs_rel']), (0.01, 0.002, 0.0))
        r, s = self.one('Voltage, DC [Offset under a waveform, 50 Ohm]')
        self.assertEqual((s['rel'], s['abs'], s['fs_rel'], s['fs_value']), (0.01, 0.002, 0.005, 10.0))

    def test_square_pulse_arb_timing(self):                      # printed p. 320
        r, s = self.one('Rise Time [Square wave into 50 Ohm]')
        self.assertEqual((r['kind'], s['abs'], s['le']), ('RISE', 8e-9, True))
        cases = {'Time [Square wave Asymmetry]': (0.01, 1e-9, 12.5e-9, 1e6),
                 'Time [Square wave Jitter (rms), below 2 MHz]': (1e-4, 525e-12, 500e-9, 1e6),
                 'Time [Square wave Jitter (rms), 2 MHz and above]': (1e-3, 75e-12, 12.5e-9, 500e-9),
                 'Time [Pulse Jitter (rms)]': (100e-6, 50e-12, 20e-9, 2000.0),
                 'Time [Arb Jitter (rms)]': (30e-6, 2.5e-9, 40e-9, 1e6)}
        for fn, (rel, ab, lo, hi) in cases.items():
            r, s = self.one(fn)
            self.assertEqual((r['kind'], r['unit']), ('TIME', 's'), fn)
            self.assertAlmostEqual(s['rel'], rel, 15)
            self.assertAlmostEqual(s['abs'], ab, 18)
            self.assertAlmostEqual(r['amp_lo'], lo, 15)
            self.assertAlmostEqual(r['amp_hi'], hi, 6)

    def test_spectral_purity_limits(self):                       # printed p. 320
        harm = {(0.0, 1e6, 0.0): -60, (0.0, 1e6, 3.0): -55, (1e6, 5e6, 0.0): -57, (1e6, 5e6, 3.0): -45, (5e6, 80e6, 0.0): -37, (5e6, 80e6, 3.0): -30}
        got = {(r['freq_lo'], r['freq_hi'], r['amp_lo']): r['specs'][0]['abs'] for r in self.rows['Sinewave Spectral Purity [Harmonic Distortion]']}
        self.assertEqual(got, harm)
        r, s = self.one('Sinewave Spectral Purity [Total Harmonic Distortion]')
        self.assertEqual((r['freq_lo'], r['freq_hi'], s['rel'], s['abs']), (0.0, 20e3, 0.002, 1e-4))
        sp = [(r['freq_lo'], r['freq_hi'], r['specs'][0]['abs']) for r in self.rows['Sinewave Spectral Purity [Spurious (non-harmonic)]']]
        self.assertEqual(sp, [(0.0, 1e6, -60), (1e6, 20e6, -50), (20e6, 80e6, -50)])
        self.assertIn('6 dBc/octave', self.rows['Sinewave Spectral Purity [Spurious (non-harmonic)]'][2]['specs'][0]['raw'])

    def test_every_range_is_one_year_only(self):
        for rs in self.rows.values():
            for r in rs:
                self.assertEqual([s['period'] for s in r['specs']], ['1 yr'])

    def test_loaded_and_default_period(self):
        self.assertEqual(self.std.model, '33250A')
        self.assertEqual(self.std.period, '1 yr')
        self.assertEqual(next(x for x in sm.standards(self.db) if x['model'] == '33250A')['rows'], 27)

    def test_lookups_by_hand(self):
        h = self.std.lookup('FREQ', 1e6)
        self.assertAlmostEqual(h.limit, 2.0, 9)                                  # 2 ppm of 1 MHz
        h = self.std.lookup('ACV', 1.0, frequency=1000.0, variant='Vpp')
        self.assertAlmostEqual(h.limit, 0.011, 12)                               # 1 % of 1 Vpp + 1 mVpp: only the printed row at exactly 1 kHz
        h = self.std.lookup('ACV', 5.0, frequency=60e6, variant='Vpp')
        self.assertAlmostEqual(h.limit, 0.301, 12)                               # 6 % of 5 Vpp + 1 mVpp
        h = self.std.lookup('ACV', 5.0, frequency=10e6, variant='Vpp')
        self.assertAlmostEqual(h.limit, 0.151, 12)                               # the shared 10 MHz edge takes the worse (10 - 50 MHz) row
        h = self.std.lookup('ACV', 1.0, frequency=100e3, variant='Vpp')
        self.assertAlmostEqual(h.limit, 0.021, 12)
        self.assertIsNone(self.std.lookup('ACV', 1.0, frequency=100e6, variant='Vpp'))
        self.assertIsNone(self.std.lookup('ACV', 1.0, frequency=1000.0))                 # a plain (V rms) AC volts lookup never reaches the Vpp rows
        h = self.std.lookup('DCV', 2.0, variant='DC Volts')
        self.assertAlmostEqual(h.limit, 0.022, 12)
        h = self.std.lookup('DCV', 2.0)
        self.assertAlmostEqual(h.limit, 0.072, 12)                               # plain lookup: the larger (under a waveform) row
        self.assertAlmostEqual(self.std.lookup('RISE', 0.0).limit, 8e-9, 18)

    def test_flags_are_on_the_sheet(self):
        text = ' '.join(p['what'] for p in self.data['problems'])
        for word in ('DERIVED', 'ASSUMED', 'ageing', 'divisor 2', 'typical', 'UNVERIFIED'):
            self.assertIn(word, text + ' '.join(self.data['notes'].values()))
        self.assertIsNone(self.data['standard']['confidence_pct'])
        self.assertIn('not specified', self.data['standard']['confidence_text'])
        self.assertIn('<=', ' '.join(r['specs'][0]['raw'] for r in self.rows['Rise Time [Square wave into 50 Ohm]']))


if __name__ == '__main__':
    unittest.main()
