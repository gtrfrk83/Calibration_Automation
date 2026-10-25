"""Temperature (thermocouple simulation) uncertainty and TAR / TUR on the handheld multimeter reports.

Sorts after test_beta*; runs with plain `python -m unittest tests.test_beta_temp_uncertainty` (no tkinter needed).

The calibrator (5522A / 5560A) sources the Type K thermocouple signal; the uncertainty of a temperature point is built from that calibrator's
published 1-year Type K SIMULATION specification in degC (specs/standards/*_standard.json, loaded by specmanager), the same way as every other
point, and TAR = half-width of the pass/fail limits / that specification.  Numbers below are worked by hand from the manual tables:

  5522A Operators Manual (R0), Chapter 1, "Temperature Calibration (Thermocouple)", printed p. 1-17 (PDF page 37), Type K, 1 year, degC:
      -200..-100  0.33     -100..-25  0.18     -25..120  0.16     120..1000  0.26     1000..1372  0.40      (90 day: 0.25 0.14 0.12 0.19 0.30)
      note [2] resolution 0.01 degC; note [3] does not include thermocouple error.
  5560A Product Specifications (Rev. 8, 6/26), "TC Specifications": Type K rows on PDF p. 17 = printed p. 16, table header and resolution on printed p. 15; read from the page image.
      The stored sheet (specs/standards/fluke_5560a_standard.json) carries the 95 % confidence / 1 year column, the same column as every other 5560A row (confidence 95 %,
      divisor 2).  1 year, 95 %, degC:  -200..-100 0.22   -100..-25 0.10   -25..120 0.09   120..1000 0.16   1000..1372 0.27
      (the 99 % / 1 year column prints 0.28 0.13 0.11 0.21 0.35; 90 day 95 %: 0.17 0.08 0.07 0.13 0.22).  Resolution 0.01 degC (printed p. 15).

Budget (uncertainty_budget): u = spec / divisor (5522A 99 % -> 2.576; 5560A 95 % column -> 2), plus the calibrator resolution / sqrt(12) when known (0.01 degC for both calibrators),
EMU = 2 * sqrt(sum u^2), rounded UP to 2 significant figures; the scope's Type K line (printed p. 13) is the CMC floor.
  5522A  (sheet at 99 %, divisor 2.576, since 2026-10-22; before: divisor 2 -> 0.17 / 0.27 / 0.19)
         0 / 100 degC: 2*sqrt((0.16/2.576)^2 + 0.002887^2) = 0.124358 -> 0.13      400: 0.201946 -> 0.21      -40: 0.139871 -> 0.14      1000: 0.310613 -> 0.32
  5560A  0 / 100 degC: 2*sqrt(0.045^2 + 0.002887^2) = 0.090185 -> 0.091   400: 0.160104 -> 0.17   -40: 0.100167 -> 0.11   1000: 0.270062 -> 0.28
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import dmm_export_harness  # noqa: E402

dmm_export_harness.stub_tk()

import re  # noqa: E402

import specmanager as sm  # noqa: E402
import tartur  # noqa: E402
import uncertainty  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

HAVE_RL = True
try:
    import reportlab  # noqa: F401
except Exception:
    HAVE_RL = False
HAVE_PDFTOTEXT = Path('/usr/bin/pdftotext').exists()

# 5522A Operators Manual p. 1-17, Type K: (lo, hi, 90 day, 1 year), degC
MANUAL_5522A_K = [(-200, -100, 0.25, 0.33), (-100, -25, 0.14, 0.18), (-25, 120, 0.12, 0.16), (120, 1000, 0.19, 0.26), (1000, 1372, 0.30, 0.40)]
SHEET_5560A_K = [(-200, -100, 0.22), (-100, -25, 0.10), (-25, 120, 0.09), (120, 1000, 0.16), (1000, 1372, 0.27)]


def pt(v, unit='degC'):
    return dict(kind='TEMP', nominal=float(v), unit=unit, range=None, frequency=None)


class Data(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = os.path.join(tempfile.mkdtemp(), 'reg.sqlite3')
        sm.seed(path=cls.db)
        cls.s22 = sm.standard('5522A', cls.db)
        cls.s56 = sm.standard('5560A', cls.db)
        cls.sc = uncertainty.load()

    def k_rows(self, std):
        return [r for r in std.rows if r['kind'] == 'TEMP' and r['direction'] == 'output' and r['unit'] == 'degC' and re.search(r'type\s*k\b', r['variant'] + r['function'], re.I)]

    # ---- the stored rows are the manual's table
    def test_5522a_rows_match_manual_p_1_17(self):
        rows = self.k_rows(self.s22)
        self.assertTrue(rows)
        for r in rows:
            m = [x for x in MANUAL_5522A_K if (x[0], x[1]) == (r['amp_lo'], r['amp_hi'])]
            self.assertEqual(len(m), 1, r['label'])
            by = {s['period']: s['abs'] for s in r['specs']}
            self.assertEqual(by['1 yr'], m[0][3], r['label'])
            if '90 day' in by:
                self.assertEqual(by['90 day'], m[0][2], r['label'])
            self.assertEqual((r['specs'][0]['rel'], r['specs'][0]['fs_rel']), (0.0, 0.0))
        self.assertEqual({(r['amp_lo'], r['amp_hi']) for r in rows}, {(x[0], x[1]) for x in MANUAL_5522A_K})

    def test_5560a_rows_match_the_laboratory_sheet(self):
        rows = self.k_rows(self.s56)
        self.assertEqual({(r['amp_lo'], r['amp_hi'], r['specs'][0]['abs']) for r in rows}, set(SHEET_5560A_K))

    # ---- hand-computed lookups
    def test_5522a_lookup_points(self):
        for v, want in ((0, 0.16), (100, 0.16), (400, 0.26), (-40, 0.18), (1000.0, 0.40), (-200, 0.33), (1372, 0.40)):
            h = self.s22.lookup_temperature(v)
            self.assertEqual(h.limit, want, v)
            self.assertEqual(h.period, '1 yr')

    def test_5560a_lookup_points(self):
        for v, want in ((0, 0.09), (100, 0.09), (400, 0.16), (-40, 0.10), (1000.0, 0.27), (-200, 0.22), (1372, 0.27)):
            self.assertEqual(self.s56.lookup_temperature(v).limit, want, v)

    def test_borders_use_the_larger_limit(self):
        self.assertEqual(self.s22.lookup_temperature(-25).limit, 0.18)       # 0.18 | 0.16
        self.assertEqual(self.s22.lookup_temperature(120).limit, 0.26)       # 0.16 | 0.26
        self.assertEqual(self.s22.lookup_temperature(-100).limit, 0.33)
        self.assertEqual(self.s56.lookup_temperature(-25).limit, 0.10)
        self.assertEqual(self.s56.lookup_temperature(120).limit, 0.16)

    def test_90_day_column_is_available_but_not_the_default(self):
        self.assertEqual(self.s22.lookup_temperature(0, period='90 day').limit, 0.12)
        self.assertEqual(self.s22.lookup_temperature(0).limit, 0.16)

    def test_negative_temperatures_are_not_mirrored_and_degF_rows_are_not_used(self):
        # the magnitude lookup would take 40 degC for -40 degC and a degF band for 100 degC; this one must not
        self.assertEqual(self.s22.lookup_temperature(-40).row['label'], '-100 °C to -25 °C')
        self.assertEqual(self.s22.lookup_temperature(-40).row['unit'], 'degC')
        self.assertEqual(self.s56.lookup_temperature(100).row['label'], '-25 to 120')

    def test_outside_the_specified_range_is_none_never_extrapolated(self):
        for std in (self.s22, self.s56):
            for v in (-200.01, -250, 1372.01, 1500, 2000):
                self.assertIsNone(std.lookup_temperature(v), v)

    def test_other_thermocouple_type_and_input_direction_are_separate(self):
        self.assertEqual(self.s22.lookup_temperature(100, tc='J').limit, 0.14)          # J, -30..150, 1 yr (p. 1-17): not the K row
        self.assertIsNone(self.s22.lookup_temperature(100, tc='Q'))
        self.assertNotEqual(self.s22.lookup_temperature(100, direction='input'), self.s22.lookup_temperature(100))

    # ---- budget
    def test_5522a_budget_hand_worked(self):
        for v, spec, rep in ((0, 0.16, 0.13), (100, 0.16, 0.13), (400, 0.26, 0.21), (-40, 0.18, 0.14)):   # 99 % sheet: spec / 2.576 (was / 2: 0.17 0.17 0.27 0.19)
            b = ub.build('TEMP', v, 'degC', standard=self.s22, scope=self.sc)
            self.assertEqual(len(b.components), 2, v)
            self.assertAlmostEqual(b.components[0].u, spec / 2.576, 12)
            self.assertAlmostEqual(b.components[1].u, 0.01 / 12 ** 0.5, 12)
            self.assertAlmostEqual(b.emu, 2 * ((spec / 2.576) ** 2 + (0.01 ** 2) / 12) ** 0.5, 12)
            self.assertEqual(b.cmc, {0: 0.10, 100: 0.10, 400: 0.16, -40: 0.11}[v])      # the scope's Type K line (p. 13): a floor, never below it
            self.assertEqual(b.reported, rep, v)
            self.assertGreaterEqual(b.reported, b.emu)
            self.assertEqual(uncertainty.format_value(b.reported, 'C'), f'{rep:.2f} °C')

    def test_5560a_budget_hand_worked(self):
        for v, spec, rep, text in ((0, 0.09, 0.10, '0.10 °C'), (100, 0.09, 0.10, '0.10 °C'), (400, 0.16, 0.17, '0.17 °C'), (-40, 0.10, 0.11, '0.11 °C'),
                                   (1000, 0.27, 0.28, '0.28 °C'), (-200, 0.22, 0.23, '0.23 °C')):
            b = ub.build('TEMP', v, 'degC', standard=self.s56, scope=self.sc)
            self.assertEqual(len(b.components), 2, v)                          # spec / 2 and the 0.01 degC resolution (5560A Product Specifications p. 15)
            self.assertAlmostEqual(b.components[0].u, spec / 2, 12)
            self.assertAlmostEqual(b.components[1].u, 0.01 / 12 ** 0.5, 12)
            self.assertAlmostEqual(b.emu, 2 * ((spec / 2) ** 2 + (0.01 ** 2) / 12) ** 0.5, 12)
            self.assertEqual(b.cmc, {0: 0.10, 100: 0.10, 400: 0.16, -40: 0.11, 1000: 0.16, -200: 0.22}[v])
            self.assertEqual(b.reported, rep, v)                 # 0 and 100 degC: the CMC (0.10) is above the budget (0.091)
            self.assertEqual(uncertainty.format_value(b.reported, 'degC'), text)

    def test_5560a_resolution_is_the_printed_0_01_degC(self):
        h = self.s56.lookup_temperature(0)
        res, src = self.s56.resolution(h)
        self.assertEqual(res, 0.01)
        self.assertIn('5560A Product Specifications', src)

    def test_resolution_edited_in_the_manager_wins(self):
        db = os.path.join(tempfile.mkdtemp(), 'r.sqlite3')
        sm.seed(path=db)
        std = sm.standard('5560A', db)
        row = std.lookup_temperature(0).row
        self.assertTrue(sm.update_row(row['id'], {'resolution': 0.1}, who='test', path=db))
        std = sm.standard('5560A', db)
        self.assertEqual(std.resolution(std.lookup_temperature(0))[0], 0.1)    # the edited value wins over the printed 0.01
        b = ub.build('TEMP', 0, 'degC', standard=std, scope=self.sc)
        self.assertEqual(len(b.components), 2)
        self.assertEqual(b.reported, 0.11)                                     # 2*sqrt(0.045^2 + (0.1/sqrt(12))^2) = 0.10693 -> rounded UP to 0.11

    def test_out_of_range_budget_has_no_value(self):
        for std in (self.s22, self.s56):
            for v in (-250, 1500):
                b = ub.build('TEMP', v, 'degC', standard=std, scope=self.sc)
                self.assertIsNone(b.reported)
                self.assertIsNone(b.hit)

    # ---- A2LA CMC rule: a CMC, where the scope has one, is a floor
    def scope_with(self, lo, hi, absolute):
        data = copy.deepcopy(self.sc.data)
        data['entries'].append(dict(basis='generate', kind='TEMP', parameter='Temperature - Generate (test entry)', standard='', notes='',
                                    bands=[dict(lo=lo, hi=hi, rel=0.0, abs=absolute)]))
        return uncertainty.Scope(data)

    def test_a_scope_temperature_cmc_would_be_a_floor(self):
        sc = self.scope_with(-200, 1372, 0.5)
        self.assertEqual(sc.dmm('TEMP', 400), 0.5)
        self.assertEqual(sc.dmm('TEMP', -40), 0.5)
        b = ub.build('TEMP', 400, 'degC', standard=self.s22, scope=sc)
        self.assertEqual(b.cmc, 0.5)
        self.assertEqual(b.reported, 0.5)                                       # never below the CMC
        self.assertEqual(ub.audit(0.4, b)[0], ub.UNDER_CMC)
        self.assertEqual(ub.build('TEMP', 400, 'degC', standard=self.s22, scope=self.scope_with(-200, 1372, 0.1)).reported, 0.21)   # budget larger than the CMC
        r = tartur.compute(pt(400), 395, 405, self.s22, sc)
        self.assertEqual(r['uncertainty'], 0.5)
        self.assertEqual(tartur.format_ratio(r['tur']), '10.0:1')
        self.assertEqual(tartur.format_ratio(r['tar']), '19.2:1')

    def test_a_cmc_band_is_signed(self):
        sc = self.scope_with(-200, -100, 0.7)
        self.assertEqual(sc.dmm('TEMP', -150), 0.7)
        self.assertIsNone(sc.dmm('TEMP', 150))                                  # +150 is not in the -200..-100 band (no magnitude mirroring)

    def test_shipped_scope_has_the_type_k_entry(self):
        for t, v in ((-200, 0.22), (-150, 0.22), (-100, 0.22), (-50, 0.11), (-25, 0.11), (0, 0.10), (120, 0.10), (400, 0.16), (1000, 0.16), (1372, 0.27)):
            self.assertEqual(self.sc.dmm('TEMP', t), v, t)       # '(> lo to hi)': an edge belongs to the lower band
        self.assertIsNone(self.sc.dmm('TEMP', 1400))
        self.assertIsNone(self.sc.dmm('TEMP', -250))

    # ---- TAR / TUR (tolerance = half the width of the limits)
    def ratios(self, std, v, low, high, unit='degC'):
        r = tartur.compute(pt(v, unit), low, high, std, self.sc)
        return tartur.format_ratio(r['tar']), tartur.format_ratio(r['tur']), r

    def test_tar_tur_5522a(self):
        self.assertEqual(self.ratios(self.s22, 0, -1.0, 1.0)[:2], ('6.2:1', '7.6:1'))            # 1/0.16 = 6.25, 1/0.13 = 7.69 (rounded DOWN; TUR was 5.8 with 0.17)
        self.assertEqual(self.ratios(self.s22, 100, 98.0, 102.0)[:2], ('12.5:1', '15.3:1'))     # 2/0.16, 2/0.13
        self.assertEqual(self.ratios(self.s22, 400, 395.0, 405.0)[:2], ('19.2:1', '23.8:1'))    # 5/0.26, 5/0.21
        self.assertEqual(self.ratios(self.s22, -40, -41.4, -38.6)[:2], ('7.7:1', '10.0:1'))     # 1.4/0.18, 1.4/0.14
        self.assertEqual(self.ratios(self.s22, 1000, 989.0, 1011.0)[:2], ('27.5:1', '34.3:1'))  # border: 0.40 -> 11/0.40, 11/0.32

    def test_tar_tur_5560a(self):
        self.assertEqual(self.ratios(self.s56, 0, -1.0, 1.0)[:2], ('11.1:1', '10.0:1'))       # TUR: 1 / 0.10 (the scope CMC is above the 0.091 budget)
        self.assertEqual(self.ratios(self.s56, 100, 98.0, 102.0)[:2], ('22.2:1', '20.0:1'))
        self.assertEqual(self.ratios(self.s56, 400, 395.0, 405.0)[:2], ('31.2:1', '29.4:1'))
        self.assertEqual(self.ratios(self.s56, -40, -41.4, -38.6)[:2], ('14.0:1', '12.7:1'))
        self.assertEqual(self.ratios(self.s56, 1000, 989.0, 1011.0)[:2], ('40.7:1', '39.2:1'))

    def test_tar_tur_use_degC_for_everything(self):
        r = self.ratios(self.s22, 0, -1.0, 1.0)[2]
        self.assertEqual((r['tolerance'], r['accuracy'], r['uncertainty']), (1.0, 0.16, 0.13))

    def test_out_of_range_is_blank(self):
        for std in (self.s22, self.s56):
            for v in (-250, 1500):
                tar, tur, r = self.ratios(std, v, v - 1, v + 1)
                self.assertEqual((tar, tur), ('', ''))
                self.assertIsNone(r['uncertainty'])

    def test_natural_unit_guard_and_no_calibrator(self):
        tar, tur, r = self.ratios(self.s22, 100, 210.2, 213.8, unit='degF')
        self.assertEqual((tar, tur), ('', ''))
        self.assertIn('not converted', r['reason'])
        r = tartur.compute(pt(100), 98, 102, None, self.sc)
        self.assertEqual((tartur.format_ratio(r['tar']), tartur.format_ratio(r['tur'])), ('', '20.0:1'))      # no calibrator: TAR blank, TUR from the scope CMC alone (0.10)
        self.assertIsNone(tartur.compute(pt(100), 98, None, self.s22, self.sc)['tar'])           # one-sided limits

    def test_other_kinds_still_blank_when_the_scope_does_not_cover_them(self):
        r = tartur.compute(dict(kind='ACV', nominal=1000.0, unit='V', range=None, frequency=1e6), 990, 1010, self.s22, self.sc)
        self.assertEqual((r['tar'], r['tur']), (None, None))
        self.assertIn('scope of accreditation', r['reason'])

    # ---- text of the uncertainty cell
    def test_format_value_temperature_and_unchanged_others(self):
        f = uncertainty.format_value
        self.assertEqual(f(0.17, 'C'), '0.17 °C')
        self.assertEqual(f(0.35, 'degC'), '0.35 °C')
        self.assertEqual(f(0.09, 'degC'), '0.090 °C')
        self.assertEqual(f(1.2, 'C'), '1.2 °C')
        self.assertEqual(f(12.0, 'C'), '12 °C')
        self.assertEqual(f(0.0, 'C'), '0 °C')
        self.assertEqual(f(None, 'C'), '')
        self.assertEqual(f(0.0001234, 'V'), '130 µV')           # untouched: SI prefix, rounded up
        self.assertEqual(f(0.16, '%'), '0.16 %')
        self.assertEqual(f(153.0, 'ohm'), '160 Ohm')


class Specs(unittest.TestCase):
    def test_every_shipped_temperature_point_is_in_degC_and_inside_the_calibrator_range(self):
        found = {}
        for f in sorted((ROOT / 'specs').glob('*_pv.json')):
            d = json.loads(f.read_text(encoding='utf-8'))
            for s in d.get('steps') or []:
                if s.get('kind') == 'TEMP':
                    found.setdefault(f.name, []).append(s)
                    self.assertEqual(s['test'], 'numeric', s['id'])
                    self.assertIn(s['base_unit'], ('C', 'degC'), s['id'])
                    self.assertEqual(s['display_unit'], '°C', s['id'])
                    self.assertTrue(-200 <= s['applied']['value'] <= 1372, s['id'])
                    self.assertEqual(s['applied']['value'], s['nominal'], s['id'])
        self.assertEqual({k: [s['id'] for s in v] for k, v in found.items()},
                         {'fluke_110_series_pv.json': ['3-36', '3-37'], 'fluke_170_series_pv.json': ['3-52', '3-53', '3-54'],
                          'fluke_287_289_pv.json': ['3-1', '3-2', '3-3'], 'fluke_87v_pv.json': ['1-50', '1-51']})

    def test_models_without_temperature_points(self):
        for name in ('klein_mm325_pv.json', 'fluke_77iv_pv.json'):
            d = json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8'))
            self.assertFalse([s for s in d['steps'] if s.get('kind') == 'TEMP' or 'temperature' in (s.get('section') or '').lower()], name)

    def test_has_uncertainty_gate(self):
        import handheld_dmm
        g = handheld_dmm.App.has_uncertainty
        base = dict(kind='TEMP', applied=dict(value=100.0, frequency=None), base_unit='C')
        self.assertTrue(g(base))
        self.assertTrue(g(dict(base, base_unit='degC')))
        self.assertFalse(g(dict(base, base_unit='degF')))
        self.assertFalse(g(dict(base, no_uncertainty=True)))
        self.assertFalse(g(dict(base, applied=None)))                                  # 'Temperature, open input' has no source
        self.assertTrue(g(dict(kind='DCV', applied=dict(value=5.0), base_unit='V')))
        self.assertFalse(g(dict(kind='VISUAL', applied=dict(value=5.0), base_unit='V')))


SCRIPT = r'''
import json, sys
sys.path[:0] = [sys.argv[1], sys.argv[1] + '/tests']
import dmm_export_harness as h
root, out, cal = sys.argv[1], sys.argv[2], sys.argv[3]
specs = ('handheld:Fluke 116', 'handheld:Fluke 179', 'handheld:Fluke 87V', 'handheld:Fluke 287', 'handheld:Fluke 115')
r = h.dump(root, out, True, specs=specs, cal_mode=cal)
res = {}
for s, v in r.items():
    res[s] = dict(pdf=str(v['pdf']), rows=[dict(Description=x['Description'], Nominal=x['Nominal'], Unc=x['Uncertainty'], UOM=x['UOM']) for x in v['rows']])
# out-of-range point through the real row / field code of the engine
app, mod, pts = h.build_engine('handheld:Fluke 116', root, cal)
p = next(q for q in pts if q['kind'] == 'TEMP' and q['nominal'] == 400)
q = dict(p, applied=dict(p['applied'], value=1500), nominal=1500.0, low='1495.0', high='1505.0')
rec = dict(reading=1500.5, result='PASS', synthetic=True, entered='1500.5')
res['out_of_range'] = dict(row=app.certificate_row(q, rec)['Uncertainty'], fields=app.certificate_fields(q))
res['in_range'] = dict(row=app.certificate_row(p, rec)['Uncertainty'], fields=app.certificate_fields(p), note=app.temperature_note())
app2, _, _ = h.build_engine('handheld:Fluke 115', root, cal)
res['no_temp_note'] = app2.temperature_note()
print('JSON>>' + json.dumps(res))
'''

LINE = re.compile(r'^\s*(?:Temperature|Type K range)\s+(-?[\d.]+) °C\s+(-?[\d.]+)\s+(-?[\d.]+)\s+°C\s+.*?(\d+(?:\.\d+)?) °C\s+(\S+)\s+(\S+)\s*$')


@unittest.skipUnless(HAVE_RL and HAVE_PDFTOTEXT, 'needs reportlab and pdftotext')
class Reports(unittest.TestCase):
    """The real export code of the handheld engine (demo readings, tkinter stubbed) with the TAR and TUR columns on."""
    EXPECT = {   # engine: [(nominal, uncertainty text, TAR, TUR)] per calibrator, from the hand-worked values in the module docstring
        '5522A': {'Fluke_116': [('0.0', '0.13 °C', '6.2:1', '7.6:1'), ('400.0', '0.21 °C', '19.2:1', '23.8:1')],
                  'Fluke_179': [('0.0', '0.13 °C', '6.2:1', '7.6:1'), ('-40.0', '0.14 °C', '7.7:1', '10.0:1'), ('400.0', '0.21 °C', '19.2:1', '23.8:1')],
                  'Fluke_87V': [('0.0', '0.13 °C', '6.2:1', '7.6:1'), ('100.0', '0.13 °C', '12.5:1', '15.3:1')],
                  'Fluke_287': [('0.0', '0.13 °C', '6.2:1', '7.6:1'), ('100.0', '0.13 °C', '12.5:1', '15.3:1'), ('1000.0', '0.32 °C', '27.5:1', '34.3:1')]},
        '5560A': {'Fluke_116': [('0.0', '0.10 °C', '11.1:1', '10.0:1'), ('400.0', '0.17 °C', '31.2:1', '29.4:1')],
                  'Fluke_179': [('0.0', '0.10 °C', '11.1:1', '10.0:1'), ('-40.0', '0.11 °C', '14.0:1', '12.7:1'), ('400.0', '0.17 °C', '31.2:1', '29.4:1')],
                  'Fluke_87V': [('0.0', '0.10 °C', '11.1:1', '10.0:1'), ('100.0', '0.10 °C', '22.2:1', '20.0:1')],
                  'Fluke_287': [('0.0', '0.10 °C', '11.1:1', '10.0:1'), ('100.0', '0.10 °C', '22.2:1', '20.0:1'), ('1000.0', '0.28 °C', '40.7:1', '39.2:1')]},
    }

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = {}
        for cal in ('5522A', '5560A'):
            d = Path(cls.tmp.name) / cal
            r = subprocess.run([sys.executable, '-c', SCRIPT, str(ROOT), str(d), 'Fluke ' + cal], capture_output=True, text=True, cwd=str(ROOT))
            if r.returncode:
                raise AssertionError(r.stdout + r.stderr)
            cls.out[cal] = json.loads(r.stdout.split('JSON>>', 1)[1])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def text(self, cal, tag):
        pdf = self.out[cal]['handheld:Fluke ' + tag.split('_', 1)[1]]['pdf']
        return subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout

    def temp_lines(self, cal, tag):
        out = []
        for line in self.text(cal, tag).splitlines():
            m = LINE.match(line)
            if m:
                out.append((m.group(1), m.group(4) + ' °C', m.group(5), m.group(6)))
        return out

    def test_every_temperature_row_prints_uncertainty_tar_and_tur(self):
        for cal, engines in self.EXPECT.items():
            for tag, want in engines.items():
                self.assertEqual(self.temp_lines(cal, tag), want, (cal, tag))

    def test_row_dicts_carry_the_uncertainty_in_degC(self):
        for cal in self.out:
            for tag, want in (('116', ['0.13 °C', '0.21 °C']), ('179', ['0.13 °C', '0.14 °C', '0.21 °C'])):
                rows = self.out[cal]['handheld:Fluke ' + tag]['rows']
                got = [r['Unc'] for r in rows if r['UOM'] == '°C']
                if cal == '5560A':
                    want = {'116': ['0.10 °C', '0.17 °C'], '179': ['0.10 °C', '0.11 °C', '0.17 °C']}[tag]
                self.assertEqual(got, want, (cal, tag))

    def test_open_input_functional_check_stays_na(self):
        for cal in self.out:
            lines = [l for l in self.text(cal, 'Fluke_116').splitlines() if 'Temperature, open input' in l]
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].rstrip().endswith('N/A        N/A') or re.search(r'N/A\s+N/A\s*$', lines[0]), lines[0])
            rows = self.out[cal]['handheld:Fluke 116']['rows']
            self.assertEqual([r['Unc'] for r in rows if 'open input' in r['Description']], [''])

    def test_out_of_range_point_prints_na(self):
        for cal in self.out:
            o = self.out[cal]['out_of_range']
            self.assertEqual(o['row'], '')
            self.assertEqual(o['fields'], dict(TAR='', TUR=''))
            i = self.out[cal]['in_range']
            self.assertNotEqual(i['row'], '')
            self.assertNotEqual(i['fields']['TAR'], '')

    def test_demo_reports_are_still_marked_and_the_footer_note_says_where_temperature_comes_from(self):
        for cal in self.out:
            for tag in ('116', '179', '87V', '287'):
                self.assertIn('DEMO DATA - NOT CALIBRATION EVIDENCE', ' '.join(self.text(cal, 'Fluke_' + tag).split()), (cal, tag))
            note = self.out[cal]['in_range']['note']
            self.assertIn(f'{cal} calibrator', note)
            self.assertIn('Type K', note)
            self.assertIn('CMC floor', note)
            self.assertEqual(self.out[cal]['no_temp_note'], '')                      # the 115 has no temperature point: nothing added

    def test_non_temperature_rows_are_untouched(self):
        # the 115 has no temperature point: its PDF carries no degC uncertainty and the Uncertainty of an ordinary point is the usual text
        for cal in self.out:
            rows = self.out[cal]['handheld:Fluke 115']['rows']
            self.assertFalse([r for r in rows if '°C' in r['Unc']])
            self.assertTrue([r for r in rows if r['Unc'].endswith(('mV', 'µV', 'Ohm', 'mOhm', 'kOhm'))])


if __name__ == '__main__':
    unittest.main()
