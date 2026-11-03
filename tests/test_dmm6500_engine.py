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

CAL_NAMES = {'5560A': 'Fluke 5560A'}              # the 5700A (alone and with the 5725A) has its own test classes below; the 5520A and 5522A are not offered (owner, 2026-11-03)
BY_REF = {p['ref']: p for p in E.POINTS}


def build(cal='5560A', reference=True):
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


class Calibrator5700A(Fast):
    """The 5700A (original; owner decision 2026-11-03): sourced by drivers/fluke_5700a.py on drivers/simulated_5700a.py, which is hand-written from the Series II guide (UNVERIFIED)."""

    @staticmethod
    def manual_ids():
        import calibrator_fit as cf
        offer = cf.make_offer('5700A', cf.dmm_requests(E.fit_requests(E.POINTS)), per_point_manual=True)
        return {r.key: why for r, why in offer.manual}

    def build(self):
        bench, ct, dt, rt = make_dmm6500_bench('5700A', reference=True)
        io = E.IO('v', 'v', 'Fluke 5700A', 9600, 'USB', transports=(dt, ct, rt), virtual=True)
        manual = self.manual_ids()
        io.is_manual = lambda p: p['id'] in manual or (p['kind'] == 'CAP' and p['source'] == 'calibrator')
        return io, bench, ct, dt

    def test_every_point_passes_the_ones_it_cannot_source_go_to_the_operators_standard(self):
        io, bench, ct, dt = self.build()
        n_manual = 0
        for p in E.POINTS:
            with self.subTest(point=p['ref']):
                reading = io.measure(p)
                self.assertTrue(E.judge(p, reading, io.last_eval.get('center')), (reading, p['nominal']))
                n_manual += bool(io.is_manual(p))
        self.assertEqual(n_manual, 25)                                           # 13 the sheet does not cover + 12 capacitance points
        io.close()

    def test_which_points_the_5700a_cannot_make(self):
        refs = sorted(p['ref'] for p in E.POINTS if p['id'] in self.manual_ids())
        self.assertEqual([r for r in refs if r.startswith('ACV')], ['ACV.750.100kHz', 'ACV.750.50kHz'])
        self.assertEqual(len([r for r in refs if '10A' in r]), 11)               # the rear 10 A range: DC, digitize and AC
        self.assertEqual(len(refs), 13)

    def test_the_5700a_is_driven_with_its_own_commands_and_ends_in_standby(self):
        io, bench, ct, dt = self.build()
        io.measure(BY_REF['DCV.10.1'])
        io.measure(BY_REF['OHM4.1000'])
        io.measure(BY_REF['ACI.1A.1000'])
        sent = ct.sent
        self.assertIn('OUT 10 V, 0 HZ', sent)
        self.assertIn('OUT 1000 OHM', sent)
        self.assertIn('EXTSENSE ON', sent)
        self.assertIn('CUR_POST NORMAL', sent)
        self.assertIn('OUT 1 A, 1000 HZ', sent)
        self.assertFalse(bench.fluke['operate'])
        self.assertFalse([c for c in sent if c.startswith(('CAL', 'FORMAT', 'DIAG', 'SP_SET'))])
        io.close()

    def test_a_fault_stops_before_the_output_is_operated(self):
        io, bench, ct, dt = self.build()
        ct.refuse = 'OUT 10 V'
        with self.assertRaises(drivers.InstrumentError):
            io.measure(BY_REF['DCV.10.1'])
        self.assertNotIn('OPER', ct.sent[-6:])
        io.close()

    def test_the_rtd_3_wire_points_use_external_sense_too(self):
        io, bench, ct, dt = self.build()
        io.measure(BY_REF['RTD3.2'])
        self.assertIn('EXTSENSE ON', ct.sent)
        io.close()


class Combo5700A5725A(Calibrator5700A):
    """The 5700A with its 5725A amplifier: the 13 points above the 5700A's own range are made through the amplifier, only the 12 capacitance points go to the operator's own standard."""

    def build(self):
        bench, ct, dt, rt = make_dmm6500_bench('5700A', reference=True)
        io = E.IO('v', 'v', 'Fluke 5700A + 5725A', 9600, 'USB', transports=(dt, ct, rt), virtual=True)
        manual = self.manual_ids()
        amp = E.amplifier_points([p for p in E.POINTS if p['id'] in manual])
        io.uses_amp = lambda p: p['id'] in amp
        io.is_manual = lambda p: (p['id'] in manual and p['id'] not in amp) or (p['kind'] == 'CAP' and p['source'] == 'calibrator')
        self.amp_ids = amp
        return io, bench, ct, dt

    test_every_point_passes_the_ones_it_cannot_source_go_to_the_operators_standard = None      # the 5700A-alone version of this test (25 operator points) does not apply

    def test_every_point_passes_and_only_capacitance_is_left_to_the_operator(self):
        io, bench, ct, dt = self.build()
        left = []
        for p in E.POINTS:
            with self.subTest(point=p['ref']):
                reading = io.measure(p)
                self.assertTrue(E.judge(p, reading, io.last_eval.get('center')), (p['ref'], reading, p['nominal']))
                if io.is_manual(p):
                    left.append(p['ref'])
        self.assertEqual(sorted(left), sorted(f'CAP.{n}' for n in range(2, 14)))
        self.assertEqual(len(self.amp_ids), 13)
        io.close()

    def test_the_amplifier_is_switched_in_with_the_output_in_standby_and_out_again_after_the_point(self):
        io, bench, ct, dt = self.build()
        io.measure(BY_REF['DCI.10A.1'])
        sent = ct.sent
        i = sent.index('BTYPE IB5725')
        self.assertLess(sent.index('STBY'), i)                                    # standby first
        self.assertLess(i, sent.index('BOOST ON'))
        self.assertLess(sent.index('BOOST ON'), sent.index('RANGELCK ON'))
        self.assertLess(sent.index('RANGELCK ON'), sent.index('OUT 10 A, 0 HZ'))
        self.assertIn('CUR_POST IB5725', sent)
        self.assertLess(sent.index('OUT 10 A, 0 HZ'), sent.index('OPER'))
        self.assertEqual([c for c in sent if '?' not in c][-1], 'CUR_POST NORMAL')
        self.assertIn('BOOST OFF', sent)
        self.assertFalse(ct.boost)
        io.close()

    def test_voltage_points_use_the_voltage_amplifier(self):
        io, bench, ct, dt = self.build()
        io.measure(BY_REF['ACV.750.100kHz'])
        self.assertIn('BTYPE VB5725', ct.sent)
        self.assertNotIn('CUR_POST IB5725', ct.sent)
        io.measure(BY_REF['ACV.750.1kHz'])                                         # the 5700A makes this one by itself: no BOOST
        self.assertEqual(ct.sent[-12:].count('BOOST ON'), 0)
        io.close()

    def test_a_missing_or_unpowered_5725a_is_an_error_before_the_output_is_operated(self):
        io, bench, ct, dt = self.build()
        ct.amp_connected = False
        with self.assertRaises(drivers.InstrumentError):
            io.measure(BY_REF['DCI.10A.1'])
        self.assertNotIn('OPER', ct.sent)
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
            row = report_pdf.point_row(E.effective(p), E.effective(p)['nominal'], False, section=p['section_title'], standard='5560A')
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
            self.assertEqual(app.cal_choices(), ['Fluke 5560A', 'Fluke 5700A', 'Fluke 5700A + 5725A'])       # no 5520A / 5522A
            self.assertIn('Fluke 5700A', app.cal_choices())
            self.assertFalse(any(app.is_manual(p) for p in app.active_points()))                     # a 5560A / 5522A sources every point
            app.cal_model.set('Fluke 5700A')
            self.assertEqual(sum(1 for p in app.active_points() if app.is_manual(p)), 25)
            self.assertIn('no capacitance', app.manual_reason(next(p for p in app.active_points() if p['ref'] == 'CAP.2')))
            app.cal_model.set('Fluke 5700A + 5725A')
            self.assertEqual(sum(1 for p in app.active_points() if app.is_manual(p)), 12)             # capacitance only
            self.assertEqual(sum(1 for p in app.active_points() if app.uses_amp(p)), 13)
            self.assertEqual(app.cal_key, '5700A')
            app.cal_model.set('Fluke 5560A')
            app.on_select()
            root.close()
        finally:
            hn.stop()


if __name__ == '__main__':
    unittest.main()
