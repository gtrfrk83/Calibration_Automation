"""The oscilloscope / generator engines (MDO4000C, 33210A / 33220A / 33250A, WaveSurfer WS4104HD) on the full uncertainty budget
(branch uncertainty-engines).  Run:  python -m unittest tests.test_scope_gen_budget      (no tkinter needed: tests/_tk_stub.py stands in for it)

Before: these engines printed the laboratory's A2LA scope CMC alone.  Now every point that has a matching standards sheet and a well defined budget prints
    reported = ceil_sig( max( budget, CMC ) )           budget = 2 * sqrt( (published accuracy / divisor)^2 [+ (resolution / sqrt 12)^2] )
exactly as the multimeter engines do (uncertainty_budget.build):
  * DC gain, DC offset, DVM DC (MDO4000C) and DC gain, offset, trigger level (WaveSurfer): the Fluke 5560A DC voltage specification (sheet at 95 %, divisor 2)
    against the scope's OSCILLOSCOPE DC CMC line (absolute volts);
  * sine-wave AC amplitude and low-frequency flatness (33210A / 33220A / 33250A): the Fluke 5790B 'Voltage, AC [Sinewave, Absolute]' specification (sheet at 99 %,
    divisor 2.576, direction 'input': the 5790B measures) against the scope's AC Voltage - Measure CMC.
Everything else stays CMC-only (input impedance, bandwidth, square-wave amplitude, time base) or blank / N/A (no sheet, no CMC).

Hand-worked numbers (sheet rows read back from specs/standards, 1 year):
  5560A DC volts 1 V (1.2 V range): 0.00064 % of reading + 1 uV = 7.4 uV  -> u = 3.7 uV, EMU = 7.4 uV                 ; 5 V (12 V range): 0.00062 % + 10 uV = 41 uV
  5790B AC volts 20 mV @ 1 kHz (22 mV range, 40 Hz-20 kHz): 110 ppm of reading + 1.3 uV = 3.5 uV -> u = 3.5 / 2.576 = 1.358696 uV, EMU = 2.717391 uV
  oscilloscope DC CMC: 1 MOhm 0.06 % of the level + 40 uV  (1 V: 640 uV; 5 V: 3.04 mV); 50 Ohm 0.26 % + 40 uV, up to 6.6 V (0.9 V: 2.38 mV; 4.5 mV: 51.7 uV)
  AC Voltage - Measure CMC at 20 mV, 1 kHz: 2.88 uV.
The budget is below 3 % of the oscilloscope DC CMC at every level, and below the AC Measure CMC at every 5790B point of the three generators, so today the
printed numbers equal the CMC-only ones (the tests below show the budget really is in the path by making it dominate: divisor patched to 0.001)."""
import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))

_spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
_stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stub)
_stub.install()

import specmanager as sm  # noqa: E402
import tartur  # noqa: E402
import uncertainty  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

SC = uncertainty.load()


def cmc_1m(v):
    return 0.0006 * abs(v) + 4e-5


def cmc_50(v):
    return 0.0026 * abs(v) + 4e-5


def dominate():
    """Make every standard's budget huge (divisor 0.001) so the budget, not the CMC, decides: proves the budget is in the path."""
    return mock.patch.object(sm.StandardSpec, 'divisor', lambda self: (0.001, 'test'))


class BudgetOptions(unittest.TestCase):
    def test_default_call_is_the_old_one(self):
        b = ub.build('DCV', 10.0, 'V', standard='5560A', scope=SC)
        self.assertAlmostEqual(b.hit.limit, 7.2e-5, 12)                    # 12 V range: 0.00062 % of 10 V + 10 uV
        self.assertAlmostEqual(b.emu, 7.2e-5, 12)                          # divisor 2, k 2
        self.assertEqual(b.cmc, SC.dmm('DCV', 10.0))                       # DMM 'DC Voltage - Generate'
        self.assertEqual(b.reported, ub.ceil_sig(max(b.emu, b.cmc)))

    def test_input_direction_and_measure_basis_5790b(self):
        self.assertIsNone(ub.build('ACV', 0.02, 'V', standard='5790B', frequency=1e3, scope=SC).hit)     # output rows only: nothing (why direction exists)
        b = ub.build('ACV', 0.02, 'V', standard='5790B', frequency=1e3, scope=SC, direction='input', basis='measure')
        self.assertAlmostEqual(b.hit.limit, 3.5e-6, 12)
        self.assertAlmostEqual(b.components[0].u, 3.5e-6 / 2.576, 12)
        self.assertAlmostEqual(b.emu, 2 * 3.5e-6 / 2.576, 12)              # 2.717391 uV (no resolution on the sheet)
        self.assertAlmostEqual(b.cmc, 2.88e-6, 12)
        self.assertEqual(b.cmc, SC.dmm('ACV', 0.02, None, 1e3, basis='measure'))
        self.assertAlmostEqual(b.value, 2.88e-6, 12)                       # the CMC is the larger today
        self.assertAlmostEqual(b.reported, 2.9e-6, 12)
        self.assertTrue(any('resolution' in n for n in b.notes))           # the sheet records none: said, not invented

    def test_cmc_override_and_value(self):
        b = ub.build('DCV', 1.0, 'V', standard='5560A', scope=SC, cmc=0.5)
        self.assertEqual(b.cmc, 0.5)
        self.assertEqual((b.value, b.reported), (0.5, 0.5))
        b = ub.build('DCV', 1.0, 'V', standard=None, scope=SC, cmc=None)
        self.assertIsNone(b.emu)
        self.assertEqual(b.value, b.cmc)
        self.assertIsNone(ub.Budget('DCV', 1, 'V').value)

    def test_audit_still_works_with_an_override(self):
        b = ub.build('DCV', 1.0, 'V', standard='5560A', scope=SC, cmc=6.4e-4)
        self.assertEqual(ub.audit(6.3e-4, b)[0], ub.UNDER_CMC)
        self.assertEqual(ub.audit(6.4e-4, b)[0], ub.OK)


class OscDc(unittest.TestCase):
    def test_hand_values(self):
        b = ub.osc_dc(1.0, '1M', '5560A', SC)
        self.assertAlmostEqual(b.hit.limit, 7.4e-6, 12)
        self.assertAlmostEqual(b.emu, 7.4e-6, 12)
        self.assertAlmostEqual(b.cmc, 6.4e-4, 12)
        self.assertAlmostEqual(b.value, 6.4e-4, 12)
        self.assertAlmostEqual(b.reported, 6.4e-4, 12)
        b = ub.osc_dc(-5.0, '1M', '5560A', SC)                             # sign never matters
        self.assertAlmostEqual(b.emu, 4.1e-5, 12)
        self.assertAlmostEqual(b.value, 3.04e-3, 12)
        b = ub.osc_dc(0.9, '50', '5560A', SC)
        self.assertAlmostEqual(b.value, 2.38e-3, 12)
        self.assertAlmostEqual(b.reported, 2.4e-3, 12)
        b = ub.osc_dc(0.0, '1M', '5560A', SC)
        self.assertAlmostEqual(b.value, 4e-5, 12)

    def test_outside_the_scope_there_is_nothing(self):
        self.assertIsNone(ub.osc_dc(10.0, '50', '5560A', SC))              # the 50 ohm line stops at 6.6 V
        self.assertIsNone(ub.osc_dc(200.0, '1M', '5560A', SC))             # the 1 MOhm line stops at 130 V

    def test_the_budget_wins_when_it_is_larger(self):
        with dominate():
            b = ub.osc_dc(1.0, '1M', '5560A', SC)
        self.assertAlmostEqual(b.emu, 2 * 7.4e-6 / 0.001, 9)               # 14.8 mV
        self.assertAlmostEqual(b.value, 0.0148, 9)
        self.assertAlmostEqual(b.reported, 0.015, 9)

    def test_missing_sheet_falls_back_to_the_cmc(self):
        b = ub.osc_dc(1.0, '1M', 'NO SUCH STANDARD', SC)
        self.assertIsNone(b.emu)
        self.assertAlmostEqual(b.value, 6.4e-4, 12)
        self.assertAlmostEqual(b.reported, 6.4e-4, 12)

    def test_a_standard_that_raises_falls_back_to_the_cmc(self):
        with mock.patch.object(ub, 'build', side_effect=RuntimeError('boom')):
            b = ub.osc_dc(1.0, '1M', '5560A', SC)
        self.assertAlmostEqual(b.value, 6.4e-4, 12)
        self.assertAlmostEqual(b.reported, 6.4e-4, 12)


class Mdo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mdo4000c_verification as M
        cls.M = M

    def point(self, pid):
        return next(p for p in self.M.POINTS if p['id'] == pid)

    def test_offset_and_dvmdc_text(self):
        p = self.point(232)                                                # OFFSET 0.9 V into 50 ohm
        self.assertEqual(self.M.uncertainty_text(p, {'reading': 0.9}), '2.4 mV')           # 2.38 mV rounded UP
        p = self.point(1228)                                               # DVM DC -5 V
        self.assertEqual(self.M.uncertainty_text(p, {'reading': -5.0}), '3.1 mV')          # 3.04 mV rounded UP
        parts = self.M.uncertainty_parts(p, {'reading': -5.0})
        self.assertAlmostEqual(parts[0], 3.04e-3, 12)
        self.assertEqual(parts[1:], ('V', 'si'))

    def test_gain_is_the_quadrature_sum_of_the_two_levels(self):
        p = self.point(124)                                                # +/-4.5 mV into 50 ohm, difference 9 mV
        each = cmc_50(0.0045)                                              # 51.7 uV
        want = 100 * math.hypot(each, each) / 0.009                        # 0.81239 %
        parts = self.M.uncertainty_parts(p, {})
        self.assertAlmostEqual(parts[0], want, 9)
        self.assertEqual(parts[1], '%')
        self.assertEqual(self.M.uncertainty_text(p, {}), '0.82 %')

    def test_the_budget_decides_when_it_is_larger(self):
        p = self.point(1228)
        with dominate():
            parts = self.M.uncertainty_parts(p, {'reading': -5.0})
        self.assertAlmostEqual(parts[0], 2 * 4.1e-5 / 0.001, 9)            # 82 mV (> the 3.04 mV CMC)
        with dominate():
            text = self.M.uncertainty_text(p, {'reading': -5.0})
        self.assertEqual(text, uncertainty.format_value(0.082, 'V'))
        p = self.point(124)
        with dominate():
            parts = self.M.uncertainty_parts(p, {})
        self.assertGreater(parts[0], 100 * math.hypot(cmc_50(0.0045), cmc_50(0.0045)) / 0.009)

    def test_tur_follows_the_printed_value(self):
        p = self.point(1228)
        r = dict(reading=-5.0, raw={'reading': -5.0}, uncertainty=self.M.uncertainty_text(p, {'reading': -5.0}))
        f = self.M.tar_tur_fields(p, r)
        self.assertEqual(f['TUR'], tartur.format_ratio(0.125 / 3.1e-3))
        self.assertEqual(f['TAR'], '>1000:1')

    def test_impedance_bandwidth_and_the_rest_stay_cmc_only_or_blank(self):
        self.assertEqual(self.M.uncertainty_text(self.point(3), {'reading': 1e6}), '160 Ohm')
        self.assertEqual(self.M.uncertainty_parts(self.point(296), {'gain': 0.9})[2], 'bw')
        with dominate():                                                   # a bigger divisor effect must not reach them
            self.assertEqual(self.M.uncertainty_text(self.point(3), {'reading': 1e6}), '160 Ohm')
            self.assertEqual(self.M.uncertainty_parts(self.point(296), {'gain': 0.9})[2], 'bw')
        for kind in ('DELTA', 'PHASE', 'DANL', 'NOISE', 'DVMAC', 'XTALK', 'SELFTEST'):
            p = next(x for x in self.M.POINTS if x['kind'] == kind)
            self.assertEqual(self.M.uncertainty_text(p, {'reading': p['nominal'] or 1.0}), 'N/A', kind)

    def test_demo_reading_does_not_change(self):
        p = self.point(232)
        self.assertEqual(self.M.demo_reading(p), self.M.demo_reading(p))   # untouched helper, deterministic


class Fgen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import fgen_verification as F
        F.configure('33220A')
        cls.F = F

    def pts(self, kind, function=None):
        return [p for p in self.F.POINTS if p['kind'] == kind and (function is None or p.get('function') == function)]

    def test_sine_amplitude_uses_the_5790b_budget_against_the_measure_cmc(self):
        p = self.pts('ACAMP', 'SIN')[0]                                    # 20 mVrms, 1 kHz
        self.assertEqual((p['nominal'], p['frequency']), (0.02, 1000.0))
        b = self.F.measure_budget(p)
        self.assertAlmostEqual(b.emu, 2 * 3.5e-6 / 2.576, 12)
        value, unit, src = self.F.uncertainty_value(p)
        self.assertEqual((unit, src), ('V', 'budget'))
        self.assertAlmostEqual(value, 2.88e-6, 12)
        self.assertEqual(self.F.point_uncertainty(p), ('2.9 µV', 'budget'))

    def test_every_sine_point_has_a_budget_and_is_never_below_the_cmc(self):
        for p in self.pts('ACAMP', 'SIN') + self.pts('LFFLAT', 'SIN'):
            b = self.F.measure_budget(p)
            self.assertIsNotNone(b, p['id'])
            cmc = SC.dmm('ACV', p['nominal'], None, p['frequency'], basis='measure')
            value, unit, src = self.F.uncertainty_value(p)
            self.assertEqual(src, 'budget')
            self.assertGreaterEqual(value, cmc)
            self.assertAlmostEqual(value, max(cmc, b.emu), 15)

    def test_the_budget_decides_when_it_is_larger(self):
        p = self.pts('ACAMP', 'SIN')[0]
        with dominate():
            value, unit, src = self.F.uncertainty_value(p)
            text, _ = self.F.point_uncertainty(p)
        self.assertAlmostEqual(value, 2 * 3.5e-6 / 0.001, 9)               # 7 mV
        self.assertEqual(text, uncertainty.format_value(7e-3, 'V'))
        f = self.F.tar_tur_fields(p)                                        # TUR follows the printed (larger) value
        with dominate():
            f2 = self.F.tar_tur_fields(p)
        self.assertNotEqual(f['TUR'], f2['TUR'])

    def test_square_wave_timebase_and_flatness_stay_as_they_were(self):
        sq = self.pts('ACAMP', 'SQU')[0]
        self.assertIsNone(self.F.measure_budget(sq))                       # the 5790B sinewave rows do not describe a square wave
        self.assertEqual(self.F.uncertainty_value(sq)[2], 'scope')
        tb = self.pts('TIMEBASE')[0]
        self.assertIsNone(self.F.measure_budget(tb))
        self.assertEqual(self.F.point_uncertainty(tb)[1], 'scope')
        before = self.F.point_uncertainty(sq)
        with dominate():
            self.assertEqual(self.F.point_uncertainty(sq), before)          # no budget path: a patched divisor cannot reach it
            self.assertEqual(self.F.uncertainty_value(sq)[2], 'scope')
        for p in self.pts('FLAT') + self.pts('SELFTEST'):
            self.assertEqual(self.F.point_uncertainty(p), ('', ''))

    def test_no_5790b_row_means_cmc_only(self):
        p = dict(self.pts('ACAMP', 'SIN')[0], nominal=2000.0)              # beyond the sheet's ranges (1000 V)
        self.assertIsNone(self.F.measure_budget(p))

    def test_reference_file_value_is_still_floored_by_the_larger_of_the_two(self):
        p = self.pts('ACAMP', 'SIN')[0]
        orig = self.F._ref_cmc
        self.F._ref_cmc = lambda: {'ACAMP': {'rel': None, 'abs': 1e-9, 'unit': 'V'}}
        try:
            value, unit, src = self.F.uncertainty_value(p)
            self.assertEqual(src, 'reference file')
            self.assertAlmostEqual(value, 2.88e-6, 12)                      # never below the scope / budget
            with dominate():
                self.assertAlmostEqual(self.F.uncertainty_value(p)[0], 7e-3, 9)
        finally:
            self.F._ref_cmc = orig


class WaveSurfer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import WaveSurfer_WS4104HD as W
        cls.W = W
        cls.app = W.RMSNoiseApp.__new__(W.RMSNoiseApp)

    def test_dc_kinds_hand_values(self):
        a = self.app
        self.assertEqual(a.scope_uncertainty_value('dcv', dict(nominal_v=1.0)), (a.scope_uncertainty_value('dcv', dict(nominal_v=-1.0))[0], 'V'))
        value, unit = a.scope_uncertainty_value('dcv', dict(nominal_v=1.0))
        self.assertAlmostEqual(value, 6.4e-4, 12)
        self.assertEqual(a.scope_uncertainty('dcv', dict(nominal_v=1.0)), '640 µV')
        self.assertAlmostEqual(a.scope_uncertainty_value('offset', dict(nominal_v=10.0))[0], 6.04e-3, 12)
        value, unit = a.scope_uncertainty_value('trigger', dict(level_v=0.3, short_v=0.28, past_v=0.32))
        self.assertAlmostEqual(value, cmc_1m(0.32), 12)                     # the larger of the two bracket steps, 1 MOhm

    def test_the_budget_decides_when_it_is_larger(self):
        a = self.app
        with dominate():
            value, unit = a.scope_uncertainty_value('dcv', dict(nominal_v=1.0))
            vt, _ = a.scope_uncertainty_value('trigger', dict(level_v=0.3, short_v=0.28, past_v=0.32))
            vo, _ = a.scope_uncertainty_value('offset', dict(nominal_v=5.0))
        self.assertAlmostEqual(value, 0.0148, 9)
        self.assertAlmostEqual(vo, 2 * 4.1e-5 / 0.001, 9)
        self.assertGreater(vt, cmc_1m(0.32))
        f = a.tar_tur_fields('dcv', dict(nominal_v=1.0, lower_v=0.99, upper_v=1.01))
        with dominate():
            f2 = a.tar_tur_fields('dcv', dict(nominal_v=1.0, lower_v=0.99, upper_v=1.01))
        self.assertEqual(f['TAR'], f2['TAR'])                               # TAR is the unscaled specification: untouched
        self.assertNotEqual(f['TUR'], f2['TUR'])

    def test_impedance_bandwidth_noise_unchanged(self):
        a = self.app
        value, unit = a.scope_uncertainty_value('impedance', dict(nominal_ohm=1e6))
        self.assertEqual((value, unit), (SC.dmm('OHM', 1e6, basis='measure'), 'ohm'))
        with dominate():
            self.assertEqual(a.scope_uncertainty_value('impedance', dict(nominal_ohm=1e6))[0], value)
            self.assertEqual(a.scope_uncertainty_value('bandwidth', dict(amplitude_vpp=0.8, high_hz=1e9))[1], 'dB')
        self.assertIsNone(a.scope_uncertainty_value('noise', {}))
        self.assertEqual(a.scope_uncertainty('noise', {}), '')

    def test_bad_rows_still_give_nothing(self):
        self.assertIsNone(self.app.scope_uncertainty_value('dcv', {}))
        self.assertIsNone(self.app.scope_uncertainty_value('nonsense', {}))


class ReportRows(unittest.TestCase):
    """The report layer: WaveSurfer rows through its real write_certificate_pdf, demo marking, and whole-export PDFs for all three engines."""

    def test_wavesurfer_rows_footer_and_demo_marking(self):
        import report_pdf
        import WaveSurfer_WS4104HD as W
        app = W.RMSNoiseApp.__new__(W.RMSNoiseApp)
        rec = dict(channel=1, scale_v_div=0.5, nominal_v=1.0, lower_v=0.99, upper_v=1.01, measured_v=1.0001, result='PASS')

        class V:
            def __init__(s, v): s.v = v
            def get(s): return s.v

        app.instrument_id, app.serial = V('A1'), V('S1')
        app.certificate_rows = lambda kind, with_uncertainty=False: app._cert_records(kind, [rec], with_uncertainty)
        app.certificate_source_records = lambda kind: [rec]
        app.any_synthetic = lambda: True
        seen = {}

        def fake(path, rows, **kw):
            seen.update(rows=rows, kw=kw)
            return len(rows)

        with mock.patch.object(report_pdf, 'write_calibration_pdf', fake), mock.patch.object(report_pdf, 'context_for', lambda a: {}), \
                mock.patch.object(W.messagebox, 'showinfo', lambda *a, **k: None), mock.patch.object(W.messagebox, 'showerror', lambda *a, **k: None):
            n = app.write_certificate_pdf('x.pdf', ['dcv'], details={'technician': 'T'})
        self.assertEqual(n, 1)
        self.assertEqual(seen['rows'][0]['Uncertainty'], '640 µV')
        self.assertIs(seen['kw']['demo'], True)                             # a demo run is still marked
        self.assertIn('5560A', seen['kw']['footer_note'])
        self.assertIn('larger value is reported', seen['kw']['footer_note'])

    @unittest.skipUnless(Path('/usr/bin/pdftotext').exists(), 'pdftotext not available')
    def test_whole_export_pdfs_carry_the_budget_rows(self):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('reportlab not installed')
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(ROOT / 'tests' / 'tartur_scopes_harness.py'), str(ROOT), tmp, 'off', '2'], capture_output=True, text=True, timeout=900)
            self.assertTrue(r.returncode == 0 and 'errors []' in r.stdout, r.stdout[-1500:] + r.stderr[-1500:])
            text = lambda n: subprocess.run(['pdftotext', '-layout', str(Path(tmp) / n), '-'], capture_output=True, text=True).stdout
            ws = text('ws_dcv.pdf')
            self.assertRegex(ws, r'2mV/Div\s+6\s+4\.84\s+7\.16\s+mV.*44 µV')       # 6 mV: 0.06 % + 40 uV = 43.6 uV, rounded up
            self.assertRegex(ws, r'1V/Div\s+3\s+2\.919\s+3\.081\s+V.*1\.9 mV')          # 3 V: 1.84 mV
            fg = text('fgen.pdf')
            self.assertRegex(fg, r'Sine 20\.00 mVrms @ 1\.000 kHz, High Z.*2\.9 µV')
            self.assertRegex(fg, r'Square 900\.0 mVrms @ 1\.000 kHz, High Z.*20 µV')
            self.assertRegex(fg, r'Sine 7\.000 Vrms @ 100\.0 kHz, High Z.*1\.2 mV')
            self.assertRegex(fg, r'Sine 1\.00 Vpp @ 10\.00 MHz, 50 ohm.*71 µHz')
            mdo = text('mdo.pdf')
            self.assertIn('Uncertainty', mdo)


if __name__ == '__main__':
    unittest.main()
