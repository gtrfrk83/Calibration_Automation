"""Fluke 5700A driver (drivers/fluke_5700a.py) against drivers/simulated_5700a.py.  NOT a recording of a real 5700A: these tests prove the driver's logic and wire text, not the
instrument's behaviour (the command source is the Series II guide; the lab unit is an original 5700A)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cmdreg  # noqa: E402
import drivers  # noqa: E402
from drivers.fluke_5700a import COMMANDS, Fluke5700A  # noqa: E402
from drivers.simulated_5700a import make_5700a_bench  # noqa: E402


def make(bus='GPIB'):
    bench, ct = make_5700a_bench(bus)
    d = Fluke5700A(ct, drivers.CommandLog(), label='5700A')
    d.open()
    return d, ct, bench


class Declarations(unittest.TestCase):
    def test_registry_clean_nothing_verified_every_command_has_a_page(self):
        reg = cmdreg.merge_commands(Fluke5700A)
        self.assertEqual([str(p) for p in cmdreg.lint_registry(reg)], [])
        self.assertEqual([k for k, c in reg.items() if c.verified], [])
        for k, c in COMMANDS.items():
            self.assertIn('p. ', c.ref, k)

    def test_no_calibration_memory_or_configuration_commands(self):
        for k, c in COMMANDS.items():
            head = c.template.split()[0].upper()
            self.assertFalse(head.startswith(('CAL_', 'FORMAT', 'DIAG', 'SP_', 'CLOCK', 'RPT_', '*PUD', 'GAL')), k)

    def test_it_cannot_make_capacitance(self):
        self.assertIn('CAP', Fluke5700A.CANNOT)
        self.assertFalse(hasattr(Fluke5700A, 'set_output_capacitance'))


class Amplifier(unittest.TestCase):
    def test_current_boost_sequence_and_back(self):
        d, ct, bench = make()
        d.amplifier_on('I')
        self.assertEqual([c for c in ct.sent if c.startswith(('BTYPE', 'CUR_POST', 'BOOST', 'RANGELCK')) and '?' not in c], ['BTYPE IB5725', 'CUR_POST IB5725', 'BOOST ON', 'RANGELCK ON'])
        d.set_output_amps(10.0, None, True)
        self.assertNotIn('CUR_POST NORMAL', ct.sent)                       # the post is already the amplifier's
        d.amplifier_off()
        self.assertEqual([c for c in ct.sent if c.startswith(('BOOST', 'RANGELCK', 'CUR_POST')) and '?' not in c][-3:], ['BOOST OFF', 'RANGELCK OFF', 'CUR_POST NORMAL'])
        self.assertFalse(ct.boost or ct.rlock)

    def test_voltage_boost_does_not_touch_the_current_post(self):
        d, ct, bench = make()
        d.amplifier_on('V')
        self.assertIn('BTYPE VB5725', ct.sent)
        self.assertFalse([c for c in ct.sent if c.startswith('CUR_POST') and '?' not in c])
        d.amplifier_off()

    def test_the_amplifier_is_only_switched_in_with_the_output_in_standby(self):
        d, ct, bench = make()
        d.operate()
        with self.assertRaises(drivers.SafetyError):
            d.amplifier_on('V')
        self.assertNotIn('BOOST ON', ct.sent)

    def test_no_amplifier_on_the_cable_is_reported(self):
        d, ct, bench = make()
        ct.amp_connected = False
        with self.assertRaises(drivers.InstrumentError):
            d.amplifier_on('I')

    def test_the_simulated_5700a_refuses_what_needs_the_amplifier(self):
        d, ct, bench = make()
        d.set_output_amps(10.0, None, True)
        self.assertEqual(ct.faults, [540])
        ct.faults.clear()
        d.set_output_volts(740.0, 100000.0)
        self.assertEqual(ct.faults, [540])


class Wire(unittest.TestCase):
    def test_outputs(self):
        d, ct, bench = make()
        d.set_output_volts(10.0, None, True)
        d.set_output_volts(1.0, 1000.0)
        d.set_output_amps(0.001, None, True)
        d.set_output_ohms(1e6)
        self.assertEqual([c for c in ct.sent if c.startswith('OUT')], ['OUT 10 V, 0 HZ', 'OUT 1 V, 1000 HZ', 'OUT 0.001 A, 0 HZ', 'OUT 1000000 OHM'])
        self.assertIn('CUR_POST NORMAL', ct.sent)
        self.assertEqual(bench.fluke['unit'], 'OHM')

    def test_operate_and_standby_are_confirmed_from_the_status_register(self):
        d, ct, bench = make()
        d.operate()
        self.assertTrue(d.is_operating())
        d.standby()
        self.assertFalse(d.is_operating())

    def test_a_calibrator_that_stays_operating_is_a_safety_error(self):
        d, ct, bench = make()
        d.operate()
        original = ct.handle

        def stuck(cmd):
            if cmd.strip().upper() == 'STBY':
                ct.sent.append(cmd)
                return None                                   # ignores STBY
            return original(cmd)
        ct.handle = stuck
        with self.assertRaises(drivers.SafetyError):
            d.standby()

    def test_faults_are_read_with_their_text_and_stop_the_caller(self):
        d, ct, bench = make()
        d.check_error('ok')
        ct.faults.append(540)
        with self.assertRaises(drivers.InstrumentError) as cm:
            d.check_error('a setting')
        self.assertIn('540', str(cm.exception))

    def test_compensation_is_confirmed_and_two_wire_comp_is_left_off(self):
        d, ct, bench = make()
        d.set_compensation('WIRE4')
        self.assertTrue(ct.extsense)
        d.set_compensation('NONE')
        self.assertFalse(ct.extsense)
        self.assertFalse(ct.rcomp)

    def test_settling_wait_times_out_when_the_output_never_settles(self):
        d, ct, bench = make()
        d.operate()
        ct.settle_polls = 10 ** 6
        with self.assertRaises(drivers.InstrumentError):
            d.wait_settled(timeout=0.05, poll=0.01)

    def test_serial_enters_the_remote_state_and_gpib_does_not(self):
        d, ct, _ = make('RS232')
        self.assertIn('REMOTE', ct.sent)
        d, ct, _ = make('GPIB')
        self.assertNotIn('REMOTE', ct.sent)

    def test_reset_uses_rst_and_ends_in_standby(self):
        d, ct, bench = make()
        d.operate()
        report = d.reset_to_defaults()
        self.assertTrue(report.ok, report.text())
        self.assertIn('*RST', ct.sent)
        self.assertFalse(bench.fluke['operate'])

    def test_wrong_model_is_refused(self):
        bench, ct = make_5700a_bench()
        ct.handle = lambda cmd: 'FLUKE,5522A,1,1' if cmd.strip() == '*IDN?' else None
        d = Fluke5700A(ct, drivers.CommandLog(), label='5700A')
        with self.assertRaises(drivers.InstrumentError):
            d.open()


if __name__ == '__main__':
    unittest.main()
