"""fluke6060a_uncertainty: uncertainty of the 6060A GIDEP points from the HP 8902A / Agilent 8563E sheets, checked against the A2LA scope
(section XII in specs/a2la_1888_03_cmc.json, sections V / VI in specs/a2la_1888_03_rf.json).  `python -m unittest tests.test_fluke6060a_uncertainty`

Hand-worked values (divisor 2 for both sheets: no confidence level printed; EMU = 2 x RSS; reported = ceil to 2 figures; CMC floor only when in scope):
  FREQ / REFFREQ / MODRATE (owner, 2026-11-03): the lab's GPS-referenced XII Frequency - Measure CMC alone, 7.1E-12 x f: 100 MHz -> 0.00071 Hz = 710 uHz,
      10 MHz -> 71 uHz, 1 kHz -> 7.1 nHz; TUR > 1000:1 (the 8902A counter spec is no longer part of the figure).
  FMDEV 10 kHz at 250 kHz: 8902A 2 % -> 200 Hz / 2 -> EMU 200 Hz; scope FM 0.15-10 MHz 2.6 % -> 260 Hz (larger) -> 260 Hz, in scope.
  FMDEV 250 kHz at 250 MHz: 8902A 1 % -> EMU 2500 Hz; scope 1.3 % -> 3250 Hz -> 3300 Hz.
  AMDEPTH 30 % at 250 MHz: 8902A 1 % of reading -> 0.3 %; no AM line 10 MHz - 1.3 GHz -> out of scope, 0.3 %.
  LEVEL_REL -10 dB at 250 MHz: linearity min(0.007 x 10, 0.02) = 0.02, one IF change 0.02, one RF change 0.04, resolution 0.01/sqrt12:
      2 x sqrt(0.01^2 + 0.01^2 + 0.02^2 + 0.002887^2) = 0.04932; scope attenuation, 10 dB on the 0-10 / 10-20 edge -> larger 0.067 -> 0.067 dB.
  HARMONIC 5 MHz +13 dBm (limit -26 dBc): 1.25 (flatness), 0.85 (scale fidelity), own 2nd harmonic: -72 dBc at -40 dBm mixer -> -49 dBc at -17 dBm;
      20 log(1 + 10^(-23/20)) = 0.5941 dB -> 2 x sqrt(0.625^2 + 0.425^2 + 0.29705^2) = 1.6242 -> 1.7 dB, out of scope.
"""
import copy
import json
import math
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fluke6060a_uncertainty as fu  # noqa: E402
import fluke6060a_verification as fv  # noqa: E402


def gidep_points():
    old = fv.SPEC_PATH
    try:
        fv.SPEC_PATH = ROOT / 'specs' / 'fluke_6060a_gidep_pv.json'
        fv.configure()
        return {p['ref']: p for p in copy.deepcopy(fv.POINTS)}
    finally:
        fv.SPEC_PATH = old
        fv.configure()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, 'registry.sqlite3')
        cls.points = gidep_points()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.saved = dict(fu.DECISIONS)

    def tearDown(self):
        fu.DECISIONS.clear()
        fu.DECISIONS.update(self.saved)

    def ev(self, ref, reading=None):
        return fu.evaluate(self.points[ref], reading=reading, path=self.db)


class Budgets(Base):
    def test_frequency_points_report_the_gps_frequency_measure_cmc_alone(self):
        """Owner 2026-11-03: frequency uncertainties are the lab's GPS-referenced A2LA XII Frequency - Measure CMC (7.1 pHz/Hz), alone (NOTES 'Frequency - Measure')."""
        for ref, hz in (('4.1 Table 2 100.00000 MHz', 1e8), ('4.1.5 10 MHz reference output', 1e7), ('4.3 1000 Hz', 1e3)):
            r = self.ev(ref)
            self.assertEqual((r.status, r.scope, r.cmc_only, r.components), (fu.OK, fu.IN, True, []), ref)
            self.assertAlmostEqual(r.cmc, 7.1e-12 * hz, places=15)
            self.assertEqual(r.reported, fu.ceil_sig(7.1e-12 * hz))
        self.assertGreater(self.ev('4.1 Table 2 100.00000 MHz').tur(), 1000)

    def test_fm_deviation_takes_the_larger_cmc(self):
        r = self.ev('4.5 Table 8 250 kHz 10 kHz')
        self.assertEqual((r.status, r.scope), (fu.OK, fu.IN))
        self.assertAlmostEqual(r.emu, 200.0, places=6)
        self.assertEqual(r.reported, 260.0)
        r = self.ev('4.5 Table 8 250 MHz 250 kHz')
        self.assertEqual(r.reported, 3300.0)

    def test_fm_above_40_khz_below_10_mhz_has_no_row(self):
        r = self.ev('4.5 Table 8 250 kHz 50 kHz')
        self.assertEqual(r.status, fu.NO_SPEC)
        self.assertEqual(r.scope, fu.OUT)
        self.assertIsNone(r.reported)

    def test_am_depth_out_of_scope_between_10_mhz_and_1_3_ghz(self):
        r = self.ev('4.4 Table 6 250 MHz 30 % at 1000 Hz')
        self.assertEqual((r.status, r.scope, r.reported), (fu.OK, fu.OUT, 0.3))
        self.assertIsNone(r.cmc)

    def test_a_carrier_below_150_khz_has_no_8902a_spec(self):
        for ref in ('4.4 Table 6 150 kHz 30 % at 1000 Hz', '4.2 Table 5 150 kHz -10 dBm relative'):
            p = copy.deepcopy(self.points[ref])
            if p.get('gen'):
                p['gen']['freq_mhz'] = 0.1
            p['description'] = p['description'].replace('150 kHz', '100 kHz')
            r = fu.evaluate(p, path=self.db)
            self.assertEqual(r.status, fu.NO_SPEC, ref)
            self.assertIn('150 kHz', r.reason)
            self.assertEqual(r.scope, fu.OUT, ref)

    def test_150_khz_am_is_in_scope_on_the_most_specific_line(self):
        """150 kHz (owner, 2026-11-03): 8902A 150 kHz-10 MHz rows 2 % (50 Hz-10 kHz) and 3 % (20 Hz-10 kHz) -> 2 % x 30 = 0.6 %; scope lines 2.4 % (50 Hz-10 kHz) and
        3.5 % (20 Hz-10 kHz) -> the narrower rate band, 2.4 % x 30 = 0.72 % (larger than the budget) -> 0.72 %, TUR 1.8 / 0.72 = 2.5."""
        r = self.ev('4.4 Table 6 150 kHz 30 % at 1000 Hz')
        self.assertEqual((r.status, r.scope), (fu.OK, fu.IN))
        self.assertAlmostEqual(r.emu, 0.6, places=9)
        self.assertAlmostEqual(r.cmc, 0.72, places=9)
        self.assertEqual(r.reported, 0.72)
        self.assertAlmostEqual(r.tur(), 1.8 / 0.72, places=6)

    def test_150_khz_relative_level_is_budgeted_but_out_of_scope(self):
        r = self.ev('4.2 Table 5 150 kHz -10 dBm relative')
        self.assertEqual((r.status, r.scope, r.reported), (fu.OK, fu.OUT, 0.05))

    def test_relative_level_uses_the_attenuation_cmc_floor(self):
        r = self.ev('4.2 Table 5 250 MHz -10 dBm relative')
        self.assertAlmostEqual(r.emu, 2 * math.sqrt(0.01 ** 2 + 0.01 ** 2 + 0.02 ** 2 + (0.01 / math.sqrt(12)) ** 2), places=9)
        self.assertEqual((r.scope, r.cmc, r.reported), (fu.IN, 0.067, 0.067))
        self.assertAlmostEqual(r.tur(), 2.5 / 0.067, places=6)

    def test_relative_level_beyond_120_db_is_out_of_scope_with_noise_term(self):
        r = self.ev('4.2 Table 5 520 MHz -127 dBm relative')
        self.assertEqual((r.status, r.scope), (fu.OK, fu.OUT))
        self.assertIn('8902A noise error', [c.name for c in r.components])
        self.assertTrue(any('UNVERIFIED' in a for a in r.assumptions))

    def test_harmonic_includes_the_analyzer_own_second_harmonic(self):
        r = self.ev('4.7 Table 11 harmonics 5 MHz')
        names = [c.name for c in r.components]
        self.assertEqual(names, ['8563E relative frequency response', '8563E log scale fidelity', '8563E own second harmonic'])
        self.assertAlmostEqual(r.components[2].limit, 20 * math.log10(1 + 10 ** (-23 / 20)), places=9)
        self.assertEqual((r.scope, r.reported, r.unit), (fu.OUT, 1.7, 'dB'))
        self.assertIsNone(r.tur())

    def test_harmonic_reading_moves_the_budget(self):
        at_limit = self.ev('4.7 Table 11 harmonics 5 MHz').emu
        near_floor = self.ev('4.7 Table 11 harmonics 5 MHz', reading=-45.0).emu
        self.assertGreater(near_floor, at_limit)

    def test_spur_with_a_different_rbw_adds_rbw_switching(self):
        offset = next(p for p in self.points.values() if p['func'] == 'SPUR' and (p.get('sa') or {}).get('kind') == 'off')
        r = fu.evaluate(offset, path=self.db)
        self.assertIn('8563E RBW switching', [c.name for c in r.components])
        absolute = self.ev('4.7 Table 12 spur 245.00000 MHz carrier 185 MHz +13 dBm')
        self.assertNotIn('8563E RBW switching', [c.name for c in absolute.components])

    def test_typed_spur_and_power_meter_have_no_spec(self):
        typed = next(p for p in self.points.values() if p['func'] == 'SPUR' and p['meas'] == 'manual')
        self.assertEqual(fu.evaluate(typed, path=self.db).status, fu.NO_SPEC)
        pm = next(p for p in self.points.values() if p['meas'] == 'level_pm')
        self.assertEqual(fu.evaluate(pm, path=self.db).status, fu.NO_SPEC)

    def test_absolute_tuned_level_needs_the_sensor_input(self):
        r = self.ev('4.2 Table 5 250 MHz -10 dBm')
        self.assertEqual(r.status, fu.NEEDS_INPUT)
        self.assertIn('11722A', r.reason)

    def test_not_tested_and_self_test_are_not_applicable(self):
        nt = next(p for p in self.points.values() if p.get('not_tested'))
        self.assertEqual(fu.evaluate(nt, path=self.db).status, fu.NOT_APPLICABLE)
        st = next(p for p in self.points.values() if p['func'] == 'SELFTEST')
        self.assertEqual(fu.evaluate(st, path=self.db).status, fu.NOT_APPLICABLE)


class Decisions(Base):
    def test_open_decisions_stay_undecided(self):
        refs = ['4.4 Table 6 250 MHz 50 % THD', '4.8 residual FM']
        refs.append(next(ref for ref, p in self.points.items() if p['func'] == 'DEVMETER' and not p.get('not_tested')))
        for ref in refs:
            self.assertEqual(self.ev(ref).scope, fu.UNDECIDED, ref)
        self.assertEqual(self.ev('4.8 residual FM').status, fu.NEEDS_DECISION)

    def test_thd_in_scope_uses_the_distortion_line(self):
        ref = '4.4 Table 6 250 MHz 50 % THD'
        self.assertEqual(self.ev(ref).scope, fu.UNDECIDED)
        fu.DECISIONS['scope.THD'] = fu.IN
        r = self.ev(ref)
        self.assertEqual(r.scope, fu.IN)
        self.assertAlmostEqual(r.cmc, 5.0 * (10 ** (1.2 / 20) - 1), places=9)
        fu.DECISIONS['scope.THD'] = fu.OUT
        self.assertEqual(self.ev(ref).scope, fu.OUT)

    def test_rf_power_percent_line_basis(self):
        fu.DECISIONS['rf_pct_basis'] = None
        self.assertEqual(fu.scope_rf_power(250e6, -50)[0], None)
        fu.DECISIONS['rf_pct_basis'] = 'power'
        self.assertAlmostEqual(fu.scope_rf_power(250e6, -50)[0], 10 * math.log10(1.008), places=9)
        fu.DECISIONS['rf_pct_basis'] = 'reading'
        self.assertAlmostEqual(fu.scope_rf_power(250e6, -50)[0], 0.4, places=9)
        self.assertEqual(fu.scope_rf_power(250e6, 0)[0], 0.069)
        self.assertEqual(fu.scope_rf_power(100e3, -50), (None, ''))


class ScopeFile(unittest.TestCase):
    def test_builder_reproduces_the_shipped_file(self):
        import runpy
        data = runpy.run_path(str(ROOT / 'specs' / 'build_a2la_cmc_rf.py'), run_name='not_main')['DATA']
        self.assertEqual(json.dumps(data, indent=1) + '\n', (ROOT / 'specs' / 'a2la_1888_03_rf.json').read_text(encoding='utf-8'))

    def test_section_vi_lines_as_printed(self):
        e = fu.rf_scope()
        self.assertEqual([b['pct'] for b in e['AM']['bands']], [2.4, 3.5, 3.5, 3.5, 3.5])
        self.assertEqual([b['pct'] for b in e['FM']['bands']], [2.6, 1.3, 5.9, 3.7, 3.7])
        self.assertEqual([b['db'] for b in e['RFATTEN']['bands']], [0.064, 0.067, 0.069, 0.082, 0.10, 0.10, 0.11, 0.11, 0.14, 0.14, 0.15, 0.22])
        self.assertFalse(any(b['f_lo'] <= 250e6 <= b['f_hi'] for b in e['AM']['bands']), 'no AM line between 10 MHz and 1.3 GHz (p. 34)')

    def test_shared_scope_file_is_untouched(self):
        kinds = {x['kind'] for x in json.loads((ROOT / 'specs' / 'a2la_1888_03_cmc.json').read_text(encoding='utf-8'))['entries']}
        self.assertFalse(kinds & {'RFPOWER', 'RFATTEN', 'AM', 'FM', 'PM', 'DIST'})


class Coverage(Base):
    def test_every_gidep_point_is_classified(self):
        for p in self.points.values():
            r = fu.evaluate(p, path=self.db)
            self.assertIn(r.status, (fu.OK, fu.NEEDS_INPUT, fu.NEEDS_DECISION, fu.NO_SPEC, fu.NOT_APPLICABLE), p['ref'])
            if r.status == fu.OK:
                self.assertTrue(r.reported and r.reported > 0, p['ref'])
                self.assertIn(r.scope, (fu.IN, fu.OUT, fu.UNDECIDED), p['ref'])
                if r.scope == fu.IN:
                    self.assertGreaterEqual(r.reported, r.cmc, p['ref'])
                if r.cmc_only:
                    self.assertEqual((r.scope, r.components), (fu.IN, []), p['ref'])
                else:
                    self.assertGreaterEqual(r.reported, r.emu * (1 - 1e-12), p['ref'])


if __name__ == '__main__':
    unittest.main()


class Report(Base):
    """The engine's report rows and the PDF footnote (owner, 2026-11-02: values not covered by the scope print with an asterisk)."""

    def rows_for(self, state_key, refs, reading=None):
        import report_pdf
        old = fv.STATE_KEY
        try:
            fv.STATE_KEY = state_key
            out = []
            for ref in refs:
                p = self.points[ref]
                unc, tur = fv.point_uncertainty(p, reading)
                out.append(report_pdf.cert_row(p['description'], p['nominal'], p['low'], p['high'], p['unit'], p['nominal'], False, section=p['section'],
                                               uncertainty=unc) | {'TAR': '', 'TUR': tur})
            return out
        finally:
            fv.STATE_KEY = old

    def test_gidep_rows_star_what_the_scope_does_not_cover(self):
        rows = self.rows_for('6060A-gidep', ['4.5 Table 8 250 MHz 250 kHz', '4.4 Table 6 250 MHz 30 % at 1000 Hz', '4.7 Table 11 harmonics 5 MHz',
                                             '4.2 Table 5 250 MHz -10 dBm relative', '4.4 Table 6 150 kHz 30 % at 1000 Hz', '4.2 Table 5 150 kHz -10 dBm relative',
                                             '4.1 Table 2 100.00000 MHz'])
        self.assertEqual([r['Uncertainty'] for r in rows], ['3.3 kHz', '0.30 % *', '1.7 dB *', '0.067 dB', '0.72 %', '0.050 dB *', '710 \u00b5Hz'])
        self.assertEqual([r['TUR'] for r in rows], ['3.7:1', '', '', '37.3:1', '2.5:1', '', '>1000:1'])

    def test_instruction_manual_procedure_is_unchanged(self):
        old = fv.STATE_KEY
        try:
            fv.STATE_KEY = fv.MODEL
            self.assertEqual(fv.point_uncertainty(self.points['4.5 Table 8 250 MHz 250 kHz'], None), ('', ''))
        finally:
            fv.STATE_KEY = old

    @unittest.skipUnless(Path('/usr/bin/pdftotext').exists(), 'pdftotext not installed')
    def test_pdf_prints_the_footnote_only_when_a_value_is_starred(self):
        try:
            import reportlab  # noqa: F401
        except Exception:
            self.skipTest('reportlab not installed')
        import report_pdf
        starred = self.rows_for('6060A-gidep', ['4.4 Table 6 250 MHz 30 % at 1000 Hz', '4.5 Table 8 250 MHz 250 kHz'])
        plain = self.rows_for('6060A-gidep', ['4.5 Table 8 250 MHz 250 kHz'])
        texts = []
        for rows in (starred, plain):
            pdf = os.path.join(self.tmp.name, f'r{len(texts)}.pdf')
            report_pdf.write_calibration_pdf(pdf, rows, header=[('Instrument ID', 'T-1')], demo=True, record_history=False)
            texts.append(subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True, check=True).stdout)
        self.assertIn('0.30 % *', texts[0])
        self.assertIn('* Not covered by the laboratory', texts[0])
        self.assertIn('certificate 1888.03', ' '.join(texts[0].split()))
        self.assertNotIn('Not covered by the laboratory', texts[1])


class DeviationMeter(Base):
    """Tables 9, 10 (owner, 2026-11-03: "the deviation error uncertainties come directly from the 96270"): the 96270A generates the FM, so its FM deviation accuracy is the
    budget. 96000 Series Product Specifications (8/2026) p. 10: +/-(3 % of setting + 240 mHz); p. 11 chart: applies for Fd <= 0.6 % of Fc (11-125 MHz), <= 0.12 % (125 MHz-4 GHz).
      10 kHz: 300.24 Hz / 2 -> EMU 300.24 Hz (+ 0.1 Hz / sqrt 12, negligible) -> 310 Hz = 0.31 kHz; TUR 3 / 0.31.   47 kHz: 1410.24 Hz -> 1.5 kHz; TUR 3 / 1.5 = 2.0."""

    def dm(self, mhz, rate, khz):
        return next(p for p in self.points.values() if p['func'] == 'DEVMETER' and p['fmsrc'] == dict(carrier_mhz=float(mhz), level_dbm=p['fmsrc']['level_dbm'],
                                                                                                          dev_khz=float(khz), rate_hz=float(rate)))

    def test_budget_from_the_96270a_fm_accuracy(self):
        r = fu.evaluate(self.dm(30, 100, 10), path=self.db)
        self.assertEqual((r.status, r.scope, r.unit), (fu.OK, fu.UNDECIDED, 'kHz'))
        self.assertAlmostEqual(r.components[0].limit, 0.30024, places=9)
        self.assertEqual(r.reported, 0.31)
        self.assertEqual(fu.evaluate(self.dm(250, 4000, 47), path=self.db).reported, 1.5)
        self.assertAlmostEqual(fu.evaluate(self.dm(500, 8000, 47), path=self.db).tur(), 2.0, places=9)

    def test_outside_the_specified_deviation_region_stays_blank(self):
        r = fu.evaluate(self.dm(30, 100, 300), path=self.db)            # 0.6 % of 30 MHz = 180 kHz
        self.assertEqual(r.status, fu.NO_SPEC)
        self.assertIn('0.6 %', r.reason)
        self.assertEqual(fu.evaluate(self.dm(500, 100, 370), path=self.db).reported, 12.0)      # 0.12 % of 500 MHz = 600 kHz: specified

    def test_report_text_is_in_hz_below_1_khz(self):
        old = fv.STATE_KEY
        try:
            fv.STATE_KEY = '6060A-gidep'
            self.assertEqual(fv.point_uncertainty(self.dm(30, 100, 10), None), ('310 Hz *', ''))
            self.assertEqual(fv.point_uncertainty(self.dm(30, 100, 47), None), ('1.5 kHz *', ''))
        finally:
            fv.STATE_KEY = old

    def test_an_old_sheet_without_the_fm_rows_says_how_to_fix_it(self):
        from unittest import mock
        real = fu._rows
        with mock.patch.object(fu, '_rows', side_effect=lambda std, function, label='': [] if function.startswith('FM Deviation') else real(std, function, label)):
            r = fu.evaluate(self.dm(30, 100, 10), path=self.db)
        self.assertEqual(r.status, fu.NO_SPEC)
        self.assertIn('Import JSON', r.reason)

    def test_the_96270a_sheet_rows_as_printed(self):
        data = json.loads((ROOT / 'specs' / 'standards' / 'fluke_96270a_standard.json').read_text(encoding='utf-8'))
        fm = next(f for f in data['functions'] if f['name'] == 'FM Deviation Accuracy [Internal Sine]')
        got = [(r['freq_lo'], r['freq_hi'], next(q['hi'] for q in r['qualifiers'] if q['tag'] == 'fd_pct_fc'), r['specs'][0]['rel'], r['specs'][0]['abs']) for r in fm['ranges']]
        self.assertEqual(got, [(9e6, 11e6, 2.0, 0.03, 0.24), (11e6, 125e6, 0.6, 0.03, 0.24), (125e6, 4e9, 0.12, 0.03, 0.24)])
        self.assertIsNone(data['standard']['confidence_pct'], 'the 99 % of the 2026 spec is an owner decision (it changes the MDO level budgets)')
