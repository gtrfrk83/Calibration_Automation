"""Keithley DMM6500 engine (dmm6500_verification.py) on the simulated bench (drivers/simulated_dmm6500.py): every point runs through the real IO / driver code, the reference meter
centres the limits it should, the thermocouple offset and the RTD conversion work, and a bad meter fails.

THE SIMULATOR IS NOT A RECORDING OF A REAL DMM6500 (bench-first workflow not done): these tests prove the engine's logic and the command flow, not the instrument's behaviour.
No tkinter needed; the window smoke test needs PySide6 (skipped without)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import dmm6500_verification as E  # noqa: E402
import drivers  # noqa: E402
import rtd_cvd  # noqa: E402
from drivers.simulated_dmm6500 import make_dmm6500_bench  # noqa: E402

CAL_NAMES = {'5522A': 'Fluke 5522A', '5560A': 'Fluke 5560A', '5520A': 'Fluke 5520A'}
BY_REF = {p['ref']: p for p in E.POINTS}


def build(cal='5522A', reference=True):
    bench, ct, dt, *rt = make_dmm6500_bench(cal, reference=reference)
    io = E.IO('v', 'v', CAL_NAMES[cal], 9600, 'USB', transports=(dt, ct, *rt), virtual=True)
    return io, bench, ct, dt, (rt[0] if rt else None)


class Fast(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(E.time, 'sleep', lambda s: None)       # the settle times are real seconds / minutes: not waited for in a test
        self.patch.start()

    def tearDown(self):
        self.patch.stop()


class EveryPoint(Fast):
    def test_every_point_passes_on_each_calibrator(self):
        for cal in CAL_NAMES:
            io, *_ = build(cal)
            for p in E.POINTS:
                with self.subTest(cal=cal, point=p['ref']):
                    reading = io.measure(p)
                    self.assertTrue(E.judge(p, reading, io.last_eval.get('center')), (reading, io.last_eval, p['nominal'], p['error']))
            io.close()

    def test_the_calibrator_is_left_in_standby_after_every_point(self):
        io, bench, *_ = build()
        for ref in ('DCV.10.1', 'ACV.1.1kHz', 'OHM4.1000', 'DCI.1A.1', 'TC.1', 'RTD4.2', 'DIGV.1.1'):
            io.measure(BY_REF[ref])
            self.assertFalse(bench.fluke['operate'], ref)
        io.close()


class ReferenceMeter(Fast):
    def test_one_ohm_limits_are_centred_on_the_reference_reading(self):
        io, bench, ct, dt, rt = build()
        p = BY_REF['OHM4.1']
        rt.gain['OHMF'] = 1.0001                       # the reference reads 100 ppm high: the limits follow it, the nominal does not
        reading = io.measure(p)
        center = io.last_eval['center']
        self.assertAlmostEqual(center, 1.0001, places=6)
        self.assertAlmostEqual(center - p['nominal'], 1.0e-4, places=6)
        self.assertTrue(E.judge(p, reading, center))
        self.assertFalse(E.judge(p, reading, 1.001))   # a reading 1 mohm away from where the reference says the source is would fail
        io.close()

    def test_without_a_reference_meter_the_limits_stay_about_the_setting(self):
        io, *_ = build(reference=False)
        io.measure(BY_REF['OHM4.1'])
        self.assertEqual(io.last_eval, {})
        io.close()

    def test_only_the_manual_reference_points_use_the_reference(self):
        used = sorted(p['ref'] for p in E.POINTS if p['ref_dmm'])
        self.assertEqual([r for r in used if r.startswith('OHM4')], ['OHM4.1', 'OHM4.10'])
        self.assertEqual(len([r for r in used if r.startswith('DCI.') and 'A.' in r]), 16)
        self.assertFalse([r for r in used if r.startswith('DCI.10A')])           # a 3458A cannot read 10 A

    def test_reference_meter_is_reset_with_the_other_standards(self):
        io, *_ = build()
        standards, uuts = io.reset_roles()
        self.assertEqual((len(standards), uuts), (2, [io.dmm]))
        io.close()


class Thermocouple(Fast):
    def test_the_measured_cable_offset_is_subtracted_from_the_source_value(self):
        io, bench, ct, dt, rt = build()
        dt.offset['VOLT:DC'] = 2.0e-6                   # a 2 uV thermal offset in the cable
        reading = io.measure(BY_REF['TC.1'])
        self.assertAlmostEqual(io._tc_offset, 2.0e-6, places=7)
        self.assertAlmostEqual(bench.fluke['volts'], -0.007659 - 2.0e-6, places=9)       # the calibrator was programmed with the table value minus the offset
        self.assertLess(abs(reading - (-190.0)), 0.2)
        io.close()


class Capacitance(Fast):
    def test_cable_reading_becomes_the_relative_offset_and_the_calibrator_sources_the_rest(self):
        io, bench, ct, dt, rt = build()
        r1 = io.measure(BY_REF['CAP.1'])                                       # the cable alone, calibrator in standby
        self.assertAlmostEqual(r1, 0.375e-9, delta=1e-12)
        self.assertTrue(E.judge(BY_REF['CAP.1'], r1))
        self.assertTrue(io.dmm.rel_is_on('CAP'))
        r5 = io.measure(BY_REF['CAP.5'])                                       # 10 nF from the calibrator, cable offset removed by REL
        self.assertAlmostEqual(r5, 10e-9, delta=BY_REF['CAP.5']['error'])
        self.assertTrue(E.judge(BY_REF['CAP.5'], r5))
        io.close()


class Rtd(unittest.TestCase):
    def test_manual_example_conversions(self):
        for ohms, want in ((18.999520, -198.8900), (99.99707, -0.0075), (189.99234, 238.6775)):
            self.assertAlmostEqual(rtd_cvd.temperature(ohms), want, places=4)

    def test_round_trip_and_ice_point(self):
        self.assertAlmostEqual(rtd_cvd.resistance(0), 100.0)
        for t in (-200, -150, -50, 0, 25, 100, 400, 850):
            self.assertAlmostEqual(rtd_cvd.temperature(rtd_cvd.resistance(t)), t, places=6)

    def test_rtd_points_are_judged_about_the_cvd_temperature_of_the_actual_resistance(self):
        for ref, low_c in (('RTD4.1', -198.89), ('RTD4.2', 0.0), ('RTD3.3', 238.6775)):
            p = BY_REF[ref]
            self.assertEqual(p['unit'], '°C')
            self.assertAlmostEqual(p['nominal'], p['example_temperature'])
            self.assertAlmostEqual(p['nominal'], low_c, delta=0.01)


class Failures(Fast):
    def test_a_meter_out_of_tolerance_fails(self):
        io, bench, ct, dt, rt = build()
        dt.gain['VOLT:DC'] = 1.001                       # 1000 ppm high: every 10 V point is far outside +/- 30 ppm
        p = BY_REF['DCV.10.1']
        reading = io.measure(p)
        self.assertFalse(E.judge(p, reading))
        io.close()

    def test_wrong_terminals_stop_the_run(self):
        io, bench, ct, dt, rt = build()
        io.virtual = False                               # a real bench: nobody flips the simulated switch for the point
        dt.front = False
        with self.assertRaises(drivers.InstrumentError):
            io.measure(BY_REF['DCV.10.1'])
        io.close()

    def test_the_calibrator_refusing_an_output_is_never_operated(self):
        io, bench, ct, dt, rt = build()
        ct.errors = ['-222,"Data out of range"']
        with self.assertRaises(drivers.InstrumentError):
            io.measure(BY_REF['DCV.10.1'])
        self.assertFalse(bench.fluke['operate'])
        io.close()

    def test_overflow_is_an_error_not_a_reading(self):
        io, bench, ct, dt, rt = build()
        dt.cfg['VOLT:DC']['range'] = 0.1
        with self.assertRaises(Exception):
            io.dmm.configure_point(dict(kind='DCV', range=0.1))
            io.cal.set_output_volts(10, None, dc=True)
            io.cal.operate_unverified()
            io.dmm.read()
        io.close()


class Reset(Fast):
    def test_the_meter_is_reset_with_rst_and_left_in_a_known_state(self):
        io, bench, ct, dt, rt = build()
        report = io.dmm.reset_to_defaults()
        self.assertTrue(report.ok, report.text())
        self.assertIn('*RST', dt.sent)
        self.assertNotIn(':SYST:POS', ' '.join(dt.sent).upper())
        io.close()

    def test_no_calibration_command_is_ever_sent(self):
        io, bench, ct, dt, rt = build()
        for p in E.POINTS[::7]:
            io.measure(p)
        sent = ' '.join(dt.sent).upper()
        for bad in ('CAL', 'SYST:POS', '*SAV', '*RCL', 'PASS'):
            self.assertNotIn(bad, sent.replace('SENS', '').replace('CALC', ''))
        io.close()


class SpecLoading(unittest.TestCase):
    def test_points_load_with_limits_and_groups(self):
        self.assertEqual(len(E.POINTS), 189)
        for p in E.POINTS:
            self.assertGreater(p['error'], 0)
            self.assertIn(p['group'], E.GROUP_TITLE)
            self.assertIn(p['terminal'], ('FRONT', 'REAR'))
        self.assertEqual({p['terminal'] for p in E.POINTS if p['group'] == 'REAR10A'}, {'REAR'})
        self.assertEqual([p['ref'] for p in E.POINTS if p['optional']][:2], ['ZR.1', 'ZR.10'])

    def test_visa_addresses(self):
        self.assertEqual(E.to_visa('192.168.1.20', 'LAN'), 'TCPIP0::192.168.1.20::inst0::INSTR')
        self.assertEqual(E.to_visa('16', 'GPIB'), 'GPIB0::16::INSTR')
        self.assertEqual(E.to_visa('USB0::0x05E6::0x6500::04000000::INSTR', 'USB'), 'USB0::0x05E6::0x6500::04000000::INSTR')
        with self.assertRaises(ValueError):
            E.to_visa('', 'USB')
        self.assertEqual(E.to_ref_visa(''), '')
        self.assertEqual(E.to_ref_visa('22'), 'GPIB0::22::INSTR')

    def test_effective_point_is_centred_on_the_reference(self):
        p = BY_REF['OHM4.1']
        q = E.effective(p, 1.0001)
        self.assertAlmostEqual(q['nominal'], 1.0001)
        self.assertAlmostEqual(q['high'] - q['low'], 2 * p['error'])

    def test_report_rows_for_every_kind_build(self):
        import report_pdf
        for ref in ('DCV.10.1', 'DIGV.1.1', 'DIGI.1A.1', 'FREQ.2', 'TC.2', 'RTD4.1', 'ZR.1', 'OHM4.1', 'CAP.2', 'ACI.1A.1000', 'DCI.10A.1'):
            p = BY_REF[ref]
            row = report_pdf.point_row(E.effective(p), E.effective(p)['nominal'], False, section=p['section_title'], standard='5522A')
            self.assertTrue(row['Description'], ref)
            self.assertTrue(row['Nominal'], ref)


try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Window(unittest.TestCase):
    def test_demo_window_builds_with_every_point_and_the_new_fields(self):
        import qt_bench_harness as QH
        from PySide6.QtWidgets import QMainWindow
        hn = QH.QtHarness().start()
        try:
            root = QMainWindow()
            app = E.App(root, True)
            QH.show(root)
            self.assertEqual(len(app.active_points()), 189)
            app.zero_checks.set('Skip')
            self.assertEqual(len(app.active_points()), 189 - 11)
            for need in ('ref_entry', 'dmm_entry', 'cal_entry', 'period_combo'):
                self.assertTrue(hasattr(app, need), need)
            self.assertIn('Fluke 5522A', app.cal_choices())
            app.on_select()
            root.close()
        finally:
            hn.stop()


if __name__ == '__main__':
    unittest.main()
