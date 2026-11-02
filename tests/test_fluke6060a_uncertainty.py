"""fluke6060a_uncertainty: uncertainty of the 6060A GIDEP points from the HP 8902A / Agilent 8563E sheets, checked against the A2LA scope
(section XII in specs/a2la_1888_03_cmc.json, sections V / VI in specs/a2la_1888_03_rf.json).  `python -m unittest tests.test_fluke6060a_uncertainty`

Hand-worked values (divisor 2 for both sheets: no confidence level printed; EMU = 2 x RSS; reported = ceil to 2 figures; CMC floor only when in scope):
  FREQ 100 MHz, 10 Hz resolution: 8902A counter +/-3 counts or 30 Hz (fc >= 100 MHz) = 30 Hz -> u 15 -> EMU 30 Hz; scope XII 7.1E-12 x 1E8 = 0.00071 Hz -> 30 Hz.
      TUR = 10 / 30 = 0.33 (the 8902A cannot support the document's +/-10 Hz).
  MODRATE 1000 Hz: 0.02 Hz + 1E-6/month x 12 x 1000 = 0.012 Hz -> 2 x sqrt(0.01^2 + 0.006^2) = 0.02332 -> 0.024 Hz.
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
    def test_frequency_counter_and_tur(self):
        r = self.ev('4.1 Table 2 100.00000 MHz')
        self.assertEqual((r.status, r.scope, r.reported, r.unit), (fu.OK, fu.IN, 30.0, 'Hz'))
        self.assertAlmostEqual(r.cmc, 7.1e-12 * 1e8, places=12)
        self.assertAlmostEqual(r.tur(), 1 / 3, places=6)

    def test_modulation_rate(self):
        r = self.ev('4.3 1000 Hz')
        self.assertEqual((r.status, r.scope), (fu.OK, fu.IN))
        self.assertAlmostEqual(r.emu, 2 * math.sqrt(0.01 ** 2 + 0.006 ** 2), places=9)
        self.assertEqual(r.reported, 0.024)

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

    def test_100_khz_carrier_is_below_the_8902a_range(self):
        for ref in ('4.4 Table 6 100 kHz 30 % at 1000 Hz', '4.2 Table 5 100 kHz -10 dBm relative'):
            r = self.ev(ref)
            self.assertEqual(r.status, fu.NO_SPEC, ref)
            self.assertIn('150 kHz', r.reason)
            self.assertEqual(r.scope, fu.OUT, ref)

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
                self.assertGreaterEqual(r.reported, r.emu * (1 - 1e-12), p['ref'])


if __name__ == '__main__':
    unittest.main()
