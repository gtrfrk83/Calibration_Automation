"""Driver-level tests of the Fluke 6060A, HP 8902A and HP 8563E drivers, their simulators and the 96270A power-meter subset.

* Registries: every command has a manual reference, the unverified ones are exactly the listed ones, reset is registered and locked, outputs are 'output' risk.
* Addresses: DEFAULT_ADDRESS 2 / 14 / 18, taken from the constructor or connect(), the transport is re-targeted, nothing else fixes an address.
* 6060A: command grammar on the wire, the LM99 learn string (decode, encode, checksum, round trip), set / read back / compare, a refused read-back raises, writes are
  never retried (read-only queries may be), IR is asked once, UNCAL, sections, steps, RF off at the end of a point.
* 8902A: the reading format and error words, the command order of each measurement, status byte, timeouts of at least 30 s, calibration helpers.
* 8563E: ID / ERR? / TS;DONE?;, read-back of every setting, the harmonic helper and the spur walk on the shared simulated bench.
* 96270A: the added power-meter subset on a tiny fake SCPI transport; the existing RF commands are pinned unchanged.
No test here has run on a real instrument and none of this is calibration data.
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cmdreg  # noqa: E402
from drivers import fluke_6060a, gpib_address, hp_8563e, hp_8902a, reference_instruments  # noqa: E402
from drivers.base import InstrumentError, SafetyError  # noqa: E402
from drivers.fluke_6060a import Fluke6060A, PRESET_LEARN, decode_learn, encode_learn, learn_checksum_ok  # noqa: E402
from drivers.hp_8563e import HP8563E  # noqa: E402
from drivers.hp_8902a import HP8902A, RecalRequired, decode_reading, encode_reading  # noqa: E402
from drivers.reference_instruments import Fluke96270A, RF_COMMANDS  # noqa: E402
from drivers.simulated import SimBench  # noqa: E402
from drivers.simulated_6060a import Sim6060ATransport, make_6060a_bench, make_rf_bench, rf_state  # noqa: E402
from drivers.simulated_8563e import Sim8563ETransport  # noqa: E402
from drivers.simulated_8902a import Sim8902ATransport  # noqa: E402
from drivers.transport import CommandLog, Transport, TransportError  # noqa: E402

UNVERIFIED_6060A = ['fe.set', 'ii.query', 'im.query', 'io.query', 'ir.query', 'iu.query', 'xa.query']
UNVERIFIED_8902A = ['cf.display', 'cf.recall.ref', 'id', 'sf.display', 'srq.read']
UNVERIFIED_8563E = ['aunits.query', 'det.query', 'err.query', 'id.query', 'mkpk.nh']
UNVERIFIED_96270A_NEW = []          # every added PMETer command was read on its rendered page; the NRP40T and the unit of the reading are flagged in the text


class _NoSleep(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('time.sleep')
        patcher.start()
        self.addCleanup(patcher.stop)


def unverified(registry):
    return sorted(k for k, c in registry.items() if not c.verified)


# ======================================================================================================================================================== registries
class Registries(unittest.TestCase):
    CASES = ((Fluke6060A, UNVERIFIED_6060A), (HP8902A, UNVERIFIED_8902A), (HP8563E, UNVERIFIED_8563E))

    def test_every_command_has_a_manual_reference_and_the_registry_is_clean(self):
        for cls, _u in self.CASES:
            reg = cmdreg.merge_commands(cls)
            self.assertEqual(cmdreg.lint_registry(reg), [], cls.__name__)
            for key, cmd in reg.items():
                self.assertTrue(cmd.ref, f'{cls.__name__} {key} has no manual reference')
                self.assertTrue(cmd.name, f'{cls.__name__} {key} has no name')

    def test_the_unverified_commands_are_exactly_the_listed_ones(self):
        for cls, want in self.CASES:
            self.assertEqual(unverified(cmdreg.merge_commands(cls)), want, cls.__name__)

    def test_reset_is_registered_and_locked(self):
        for cls, _u in self.CASES:
            reg = cmdreg.merge_commands(cls)
            self.assertEqual(reg['reset'].risk, 'locked')
            self.assertFalse(cmdreg.is_overridable(reg['reset'])[0])
        self.assertEqual(Fluke6060A.COMMANDS['reset'].template, 'RC98')
        self.assertEqual(HP8902A.COMMANDS['reset'].template, 'IP')
        self.assertEqual(HP8563E.COMMANDS['reset'].template, 'IP;')

    def test_outputs_and_destructive_queries_cannot_be_overridden(self):
        reg = cmdreg.merge_commands(Fluke6060A)
        for key in ('ro.on', 'ro.off'):
            self.assertEqual(reg[key].risk, 'output')
            self.assertFalse(cmdreg.is_overridable(reg[key])[0])
        self.assertEqual(reg['ir.query'].risk, 'locked')                       # IR clears what it reports
        for key in ('cal.on', 'cal.off', 'zero', 'save.cal', 'cal.power', 'cf.ref', 'cf.pair'):
            self.assertEqual(cmdreg.merge_commands(HP8902A)[key].risk, 'locked', key)
        self.assertEqual(cmdreg.merge_commands(HP8563E)['err.query'].risk, 'locked')   # ERR? clears the list

    def test_a_query_can_only_be_asked_and_a_set_only_sent(self):
        drv = Fluke6060A(make_6060a_bench()[1])
        with self.assertRaises(InstrumentError):
            drv.ask('fr.set', mhz=100.0)
        with self.assertRaises(InstrumentError):
            drv.send('lm.query', mem=99)
        with self.assertRaises(InstrumentError):
            drv.query_retry('fr.set', values={'mhz': 100.0})


# ======================================================================================================================================================== addresses
class _AddressedTransport(Transport):
    """Only the `address` attribute of a VISA transport matters here."""

    def __init__(self, address):
        self.address = self.name = address
        self.opened = False

    def open(self): self.opened = True
    def close(self): self.opened = False


class Addresses(_NoSleep):
    def test_default_addresses(self):
        self.assertEqual((Fluke6060A.DEFAULT_ADDRESS, HP8902A.DEFAULT_ADDRESS, HP8563E.DEFAULT_ADDRESS), (2, 14, 18))
        for cls, want in ((Fluke6060A, 2), (HP8902A, 14), (HP8563E, 18)):
            self.assertEqual(cls(make_6060a_bench()[1]).address, want)

    def test_constructor_and_connect_parameters_and_the_transport_is_retargeted(self):
        for cls, default in ((Fluke6060A, 2), (HP8902A, 14), (HP8563E, 18)):
            t = _AddressedTransport('GPIB1::5::INSTR')
            drv = cls(t, address=9)
            self.assertEqual(drv.address, 9)
            self.assertEqual(gpib_address.address_of(t.address), 5)           # not touched before connect
            gpib_address.retarget(t, drv.address)
            self.assertEqual(t.address, 'GPIB1::9::INSTR')                    # the board number is kept
            self.assertEqual(cls(_AddressedTransport('GPIB0::7::INSTR')).address, 7)    # an address already in the transport is adopted
            drv.set_address('12')
            self.assertEqual(drv.address, 12)
            self.assertNotEqual(drv.address, default)

    def test_connect_with_an_address_retargets_the_visa_resource(self):
        t = _AddressedTransport('GPIB0::2::INSTR')
        drv = Fluke6060A(t)
        with self.assertRaises(Exception):
            drv.connect(address=4)                                            # nothing answers on this fake transport: the connect fails, but only after the retarget
        self.assertEqual(t.address, 'GPIB0::4::INSTR')

    def test_bad_addresses_are_refused(self):
        for bad in (31, -1, 'x', True, None.__class__):
            with self.assertRaises(InstrumentError):
                gpib_address.check_address(bad)
        with self.assertRaises(InstrumentError):
            Fluke6060A(make_6060a_bench()[1], address=40)

    def test_no_driver_hard_codes_a_resource_string(self):
        for name in ('fluke_6060a', 'hp_8902a', 'hp_8563e'):
            text = (ROOT / 'drivers' / f'{name}.py').read_text(encoding='utf-8')
            self.assertNotRegex(text, r'GPIB\d*::\d', name)
            self.assertEqual(len(re.findall(r'DEFAULT_ADDRESS\s*=\s*\d+', text)), 1, name)

    def test_the_address_cannot_change_while_connected(self):
        bench, t = make_6060a_bench()
        drv = Fluke6060A(t).connect()
        with self.assertRaises(InstrumentError):
            drv.set_address(5)


# ======================================================================================================================================================== 6060A
def connected_6060a(**kw):
    bench, t = make_6060a_bench()
    log = CommandLog()
    drv = Fluke6060A(t, log, **kw)
    drv.connect()
    return bench, t, drv, log


class LearnString(unittest.TestCase):
    def test_the_preset_memory_decodes_to_the_manual_values(self):
        s = decode_learn(PRESET_LEARN)
        self.assertEqual((s['frequency_hz'], s['amplitude_dbm'], s['am_depth_pct'], s['fm_dev_hz']), (300_000_000, -10.0, 30, 5000.0))
        self.assertEqual((s['freq_step_hz'], s['amp_step'], s['am_step_pct'], s['fm_step_hz']), (1_000_000, 1.0, 1, 100.0))
        self.assertEqual((s['mod_rate_hz'], s['step_function'], s['correction'], s['fixed_range']), (1000, 'freq', 'all_on', False))
        self.assertFalse(any(s[k] for k in ('int_am', 'ext_am', 'int_fm', 'ext_fm', 'ext_ref', 'rel_freq', 'rel_amp')))
        self.assertTrue(learn_checksum_ok(PRESET_LEARN))

    def test_the_printed_p_2_46_spelling_fails_its_checksum(self):
        printed = PRESET_LEARN.replace('KDAA', 'KKAA')                         # the typo of the manual's text page; Fig. 2-7 shows KD
        self.assertFalse(learn_checksum_ok(printed))
        with self.assertRaises(InstrumentError):
            decode_learn(printed)

    def test_encode_decode_round_trip(self):
        self.assertEqual(encode_learn(decode_learn(PRESET_LEARN)), PRESET_LEARN)
        state = dict(frequency_hz=123_456_780, amplitude_dbm=-87.3, am_depth_pct=45, fm_dev_hz=12_340.0, fm_res_hz=10.0, rf_on=True, int_am=True, ext_fm=True, mod_rate_hz=400,
                     ext_mod_level='valid', step_function='ampl', freq_step_hz=2_500_000, amp_step=6.0, correction='all_off', fixed_range=True, rel_amp=True, mod_display='FM')
        text = encode_learn(state)
        self.assertEqual(len(text), 64)
        self.assertTrue(learn_checksum_ok(text))
        back = decode_learn(text)
        for key, want in state.items():
            self.assertEqual(back[key], want, key)

    def test_bad_strings_are_refused(self):
        for bad in (PRESET_LEARN[:-1], PRESET_LEARN + 'A', PRESET_LEARN[:-1] + 'Q', PRESET_LEARN[:-1] + 'B', ''):
            with self.assertRaises(InstrumentError, msg=bad):
                decode_learn(bad)

    def test_a_volts_display_is_converted_and_refused_by_compare(self):
        state = decode_learn(PRESET_LEARN)
        self.assertEqual(state['amplitude_units'], 'dBm')

    def test_rejected_and_uncal_fields(self):
        self.assertEqual(fluke_6060a.parse_fields('001,000,000'), (1, 0, 0))
        self.assertEqual(fluke_6060a.parse_fields('000000400'), (0, 0, 0o400))
        self.assertEqual(fluke_6060a.parse_fields('00002,00000,00000'), (2, 0, 0))
        self.assertEqual(fluke_6060a.describe_fields((0, 1, 0), fluke_6060a.REJECT_BITS), ['frequency not between 0.1 and 1050 MHz'])


class SixtyConnect(_NoSleep):
    def test_connect_sequence_and_output_is_off(self):
        bench, t, drv, _log = connected_6060a()
        self.assertEqual(t.sent[0], 'ID')                                      # the model check comes first
        self.assertEqual(t.cleared, 1)                                         # then the device clear ...
        self.assertEqual(t.sent[1], 'RO0')                                     # ... and RF goes off at once (the clear itself turns RF on)
        self.assertIn('RC98', t.sent)
        self.assertLess(t.sent.index('RO0'), t.sent.index('RC98'))
        self.assertIn('CE', t.sent)
        self.assertIn('@4', t.sent)                                            # VM1, LF terminator
        self.assertIn('II', t.sent)
        self.assertIn('IO', t.sent)
        self.assertFalse(rf_state(bench)['rf_on'])
        self.assertEqual(drv.address, 2)

    def test_the_wrong_instrument_is_refused(self):
        bench, t = make_6060a_bench()
        t.handle = lambda text: 'FLUKE,5560A' if text == 'ID' else None
        with self.assertRaises(InstrumentError):
            Fluke6060A(t).connect()

    def test_option_651_is_found_by_io(self):
        bench, t = make_6060a_bench()
        t.io = (3, 1 | 8, 2)
        drv = Fluke6060A(t).connect()
        self.assertTrue(drv.low_rate_fm)
        self.assertTrue(drv.options['rear_output'] and drv.options['nv_memory'])
        drv.fm(9.99)
        with self.assertRaises(InstrumentError):
            drv.fm(20.0)

    def test_io_written_as_three_digits(self):
        bench, t = make_6060a_bench()
        t.io = (3, 5, 2)
        t.handle = (lambda orig: lambda text: '352' if text == 'IO' else orig(text))(t.handle)
        drv = Fluke6060A(t).connect()
        self.assertEqual((drv.options['field2'], drv.low_rate_fm), (5, False))


class SixtySetters(_NoSleep):
    def setUp(self):
        super().setUp()
        self.bench, self.t, self.drv, self.log = connected_6060a()
        self.t.sent.clear()

    def test_frequency_wire_text_read_back_and_state(self):
        state = self.drv.set_frequency(111.1111)
        self.assertEqual(self.t.sent[:3], ['CE', 'FR111.11110MZ', 'IR'])
        self.assertEqual(state['frequency_hz'], 111_111_100)
        self.assertEqual(rf_state(self.bench)['frequency_hz'], 111_111_100)
        self.assertIn('LM99', self.t.sent)

    def test_level_wire_text(self):
        self.drv.set_level(-7.5)
        self.assertIn('AP-7.5DB', self.t.sent)
        self.assertEqual(rf_state(self.bench)['amplitude_dbm'], -7.5)
        self.assertEqual(self.drv.last_state['amplitude_dbm'], -7.5)

    def test_out_of_range_values_are_refused_before_anything_is_sent(self):
        for call in (lambda: self.drv.set_frequency(0.05), lambda: self.drv.set_frequency(1100), lambda: self.drv.set_level(14.0), lambda: self.drv.set_level(-140.0),
                     lambda: self.drv.am(120), lambda: self.drv.fm(150), lambda: self.drv.am(30, rate_hz=500), lambda: self.drv.rf('maybe')):
            with self.assertRaises(InstrumentError):
                call()
        self.assertEqual(self.t.sent, [])

    def test_uncal_level_only_with_allow_uncal(self):
        self.drv.set_level(15.0, allow_uncal=True)
        self.assertEqual(rf_state(self.bench)['amplitude_dbm'], 15.0)
        self.drv.set_level(-140.0, allow_uncal=True)

    def test_a_wrong_read_back_raises_and_the_write_is_sent_once(self):
        orig = self.t._command

        def ignore_fr(head, num, suffix):
            return None if head == 'FR' else orig(head, num, suffix)
        self.t._command = ignore_fr
        with self.assertRaises(InstrumentError) as ctx:
            self.drv.set_frequency(200.0)
        self.assertIn('read-back refused', str(ctx.exception))
        self.assertIn('frequency_hz', str(ctx.exception))
        self.assertEqual(sum(1 for s in self.t.sent if s.startswith('FR')), 1)

    def test_a_failed_write_is_not_retried_but_a_failed_read_only_query_is(self):
        self.bench.fail_next = 'AP'
        with self.assertRaises(TransportError):
            self.drv.set_level(-20.0)
        self.assertEqual([s for s in self.t.sent if s.startswith('AP')], [])   # the one attempt failed; there was no second one
        self.bench.fail_next = 'LM'
        state = self.drv.learn()                                               # LM99 is read-only: the retry succeeds
        self.assertEqual(state['frequency_hz'], 300_000_000)
        self.assertEqual(self.t.sent.count('LM99'), 1)

    def test_ir_is_asked_once_and_never_retried(self):
        self.bench.fail_next = 'IR'
        with self.assertRaises(TransportError):
            self.drv.set_frequency(150.0)
        self.assertEqual(self.t.sent.count('IR'), 0)
        self.assertEqual(sum(1 for s in self.t.sent if s.startswith('FR')), 1)

    def test_a_rejected_entry_is_found_named_and_cleared_by_ir(self):
        self.drv.send('fr.set', mhz=2000.0)                                    # the driver itself would refuse this; send it raw
        with self.assertRaises(InstrumentError) as ctx:
            self.drv.check_rejected('raw frequency')
        self.assertIn('frequency not between 0.1 and 1050 MHz', str(ctx.exception))
        self.assertEqual(self.drv.rejected_entries()[0], False)               # IR cleared them
        self.assertEqual(self.t.sent.count('IR'), 2)

    def test_ir_reply_layouts(self):
        for layout in ('groups', 'single'):
            self.t.ir_format = layout
            self.drv.send('ap.set', dbm=0.0)
            self.drv.send('am.set', pct=120.0)                                  # AM depth 0 to 99 only
            bad, text = self.drv.rejected_entries()
            self.assertTrue(bad)
            self.assertIn('AM depth not between 0 and 99 %', text)

    def test_syntax_error_discards_the_rest_of_the_message(self):
        self.drv.write('XX,FR200MZ')
        self.assertEqual(rf_state(self.bench)['frequency_hz'], 300_000_000)
        self.assertTrue(self.drv.rejected_entries()[0])

    def test_am_internal_and_external(self):
        state = self.drv.am(30, 'int', 400)
        self.assertEqual(self.t.sent[:6], ['CE', 'MR0', 'AM30PC', 'AE0', 'AI1', 'IR'])
        self.assertTrue(state['int_am'] and not state['ext_am'])
        self.assertEqual((state['am_depth_pct'], state['mod_rate_hz']), (30, 400))
        state = self.drv.am(50, 'ext')
        self.assertTrue(state['ext_am'] and not state['int_am'])
        self.assertEqual(state['ext_mod_level'], 'valid')
        self.t.ext_level = 'ext_lo'
        with self.assertRaises(InstrumentError):                               # EXT LO: the 1 V peak input is too low
            self.drv.am(50, 'ext')

    def test_am_above_90_percent_is_uncal(self):
        with self.assertRaises(InstrumentError) as ctx:
            self.drv.am(95)
        self.assertIn('UNCAL', str(ctx.exception))
        self.assertIn('AM depth above 90 %', str(ctx.exception))
        self.drv.am(95, allow_uncal=True)

    def test_fm_internal_and_deviation_resolution(self):
        state = self.drv.fm(5.0, 'int', 1000)
        self.assertEqual(self.t.sent[:6], ['CE', 'MR1', 'FM5KZ', 'FE0', 'FI1', 'IR'])
        self.assertEqual((state['fm_dev_hz'], state['int_fm'], state['ext_fm']), (5000.0, True, False))
        self.assertEqual(self.drv.fm(12.34)['fm_dev_hz'], 12300.0)                  # 3 significant digits are sent
        with self.assertRaises(InstrumentError):
            self.drv.fm(0.05)                                                  # below 100 Hz: UNCAL

    def test_mod_off(self):
        self.drv.am(30)
        self.drv.fm(5)
        state = self.drv.mod_off()
        self.assertFalse(any(state[k] for k in ('int_am', 'ext_am', 'int_fm', 'ext_fm')))

    def test_rf_on_off_end_of_point_and_a_failed_off_is_a_safety_error(self):
        self.assertTrue(self.drv.rf('on')['rf_on'])
        self.assertTrue(rf_state(self.bench)['rf_on'])
        self.assertFalse(self.drv.end_point()['rf_on'])
        self.assertEqual(self.t.sent[-3:][:1], ['RO0'])
        self.drv.rf(True)
        orig = self.t._command
        self.t._command = lambda head, num, suffix: None if head == 'RO' else orig(head, num, suffix)
        with self.assertRaises(SafetyError):
            self.drv.end_point()

    def test_steps(self):
        self.drv.set_frequency(100.0)
        self.drv.set_step('freq', 10.0)
        self.t.sent.clear()
        state = self.drv.step('freq', 3)
        self.assertEqual(self.t.sent.count('FU'), 3)
        self.assertEqual(state['frequency_hz'], 130_000_000)
        self.assertEqual(state['step_function'], 'freq')
        self.assertEqual(self.drv.step('freq', -1)['frequency_hz'], 120_000_000)
        self.drv.set_level(11.0)
        self.drv.set_step('level', 6.0)
        self.t.sent.clear()
        self.assertEqual(self.drv.step_level(-4)['amplitude_dbm'], -13.0)
        self.assertEqual(self.t.sent.count('LD'), 4)
        self.assertEqual(self.drv.set_step('am', 5)['am_step_pct'], 5)
        self.assertEqual(self.drv.set_step('fm', 0.5)['fm_step_hz'], 500.0)
        with self.assertRaises(InstrumentError):
            self.drv.step_level(10)                                           # +11 - 60 dB would leave the calibrated range
        with self.assertRaises(InstrumentError):
            self.drv.step('freq', 0)

    def test_sections(self):
        for n, level in ((0, 12.0), (1, 6.0), (2, 0.0), (3, -12.0)):
            self.assertEqual(self.drv.select_section(n)['amplitude_dbm'], level)
        for n, code in ((4, 'SP83'), (5, 'SP84'), (6, 'SP85'), (7, 'SP86')):
            self.t.sent.clear()
            state = self.drv.select_section(n)
            self.assertIn('AP-12.0DB', self.t.sent)
            self.assertLess(self.t.sent.index('AP-12.0DB'), self.t.sent.index(code))     # AP-12DB first, then SPnn
            self.assertEqual(self.t.alt_section_active, int(code[2:]))
            self.assertFalse(state['rf_on'])                                    # SP8x turns RF on; the driver puts RO0 back
            self.assertEqual(state['correction'], 'all_on')
        self.assertTrue(self.drv.select_section(6, rf_on=True)['rf_on'])
        self.drv.set_level(0.0)
        self.assertIsNone(self.t.alt_section_active)                            # a new amplitude entry restores the default attenuators
        with self.assertRaises(InstrumentError):
            self.drv.select_section(8)

    def test_sections_need_am_off(self):
        self.drv.am(30)
        with self.assertRaises(InstrumentError):
            self.drv.select_section(4)
        self.drv.mod_off()
        self.drv.select_section(4)

    def test_uncal_codes_and_rf_off_is_not_uncal(self):
        codes, text = self.drv.uncal()
        self.assertEqual(codes[2] & 0o400, 0)                                   # RF output off is shown by IU as 400 but it is not counted
        self.assertTrue(text.startswith('none'))
        self.drv.set_level(13.0)
        with self.assertRaises(InstrumentError):
            self.drv.am(50)                                                      # +13 dBm with 50 % AM: peak above +13 dBm
        codes, text = self.drv.uncal()
        self.assertTrue(codes[2] & 0o002)
        self.assertIn('peak (AM) amplitude above +13 dBm', text)

    def test_hardware_attenuation_reads_xa(self):
        self.drv.set_level(-77.0)
        self.assertEqual(self.drv.hardware_attenuation(), 15)

    def test_wait_valid_srq_polls_until_bit_16(self):
        bench, t = make_6060a_bench()
        t.valid_after_polls = 3
        drv = Fluke6060A(t, settle='srq').connect()
        self.assertIn('SM16', t.sent)
        self.assertIn('@0', t.sent)
        drv.set_frequency(100.0)
        self.assertEqual(rf_state(bench)['frequency_hz'], 100_000_000)
        with self.assertRaises(InstrumentError):
            Fluke6060A(t, settle='bogus')

    def test_the_srq_method_needs_a_transport_that_can_poll(self):
        class NoPoll(Sim6060ATransport):
            read_stb = None
        bench = SimBench()
        drv = Fluke6060A(NoPoll(bench), settle='srq')
        with self.assertRaises(InstrumentError):
            drv.connect()

    def test_cleanup_switches_rf_off_and_never_raises(self):
        self.drv.rf('on')
        self.drv.cleanup()
        self.assertTrue(self.drv.output_off_confirmed)
        self.assertFalse(rf_state(self.bench)['rf_on'])
        self.bench.fail_next = 'RO'
        self.drv.cleanup()
        self.assertFalse(self.drv.output_off_confirmed)

    def test_context_manager_ends_with_rf_off(self):
        bench, t = make_6060a_bench()
        with Fluke6060A(t) as drv:
            drv.rf(True)
        self.assertFalse(rf_state(bench)['rf_on'])

    def test_reset_to_defaults_order_and_known_state(self):
        self.drv.rf('on')
        self.drv.am(40)
        self.t.sent.clear()
        report = self.drv.reset_to_defaults()
        self.assertTrue(report.ok, report.text())
        self.assertEqual(self.t.sent[0], 'RC98')
        self.assertEqual(self.t.sent[1], 'CE')
        self.assertIn('IR', self.t.sent)
        self.assertIn('RO0', self.t.sent)
        s = rf_state(self.bench)
        self.assertFalse(s['rf_on'] or s['int_am'])
        self.assertEqual(s['frequency_hz'], 300_000_000)

    def test_a_failed_reset_step_stops_the_run(self):
        self.bench.fail_next = 'RC98'
        report = self.drv.reset_to_defaults()
        self.assertFalse(report.ok)
        self.assertEqual(report.failed_step.name, 'reset (RC98)')

    def test_the_command_log_holds_every_write_and_no_secret(self):
        self.drv.set_frequency(100.0)
        text = '\n'.join(self.log.lines())
        self.assertIn('FR100.00000MZ', text)
        self.assertNotIn('password', text.lower())

    def test_override_of_a_normal_command_is_logged_and_output_commands_are_not_overridable(self):
        rejected = self.drv.use_commands({'fr.set': 'FR{mhz:.5f}MZ', 'ro.off': 'RO1'})
        self.assertEqual([r[0] for r in rejected], ['ro.off'])


# ======================================================================================================================================================== 8902A
def connected_8902a(rf=True, mhz=100.0, dbm=-10.0, errors=None):
    bench, t6, t8902, _t8563 = make_rf_bench()
    if errors:
        t8902.errors.update(errors)
    src = Fluke6060A(t6).connect()
    src.set_frequency(mhz)
    src.set_level(dbm)
    if rf:
        src.rf('on')
    t8902.timeouts = []
    orig = t8902.set_timeout
    t8902.set_timeout = lambda seconds: (t8902.timeouts.append(seconds), orig(seconds))
    rx = HP8902A(t8902, CommandLog())
    rx.connect()
    t8902.sent.clear()
    return bench, src, rx, t8902


class Reading(unittest.TestCase):
    def test_the_manual_examples(self):
        self.assertEqual(decode_reading('+0096921346E+01'), 969_213_460.0)       # 969.21346 MHz (p. 3-19)
        self.assertEqual(decode_reading('+0000003492E+01'), 34_920.0)            # 34.92 kHz
        self.assertEqual(decode_reading('-0000012500E-02'), -125.0)
        self.assertEqual(decode_reading(' +0096921346E+01\r\n'), 969_213_460.0)

    def test_error_words_raise_with_the_error_number(self):
        with self.assertRaises(InstrumentError) as ctx:
            decode_reading('+9000000200E+01')
        self.assertIn('error 2', str(ctx.exception))
        self.assertIn('input level too high', str(ctx.exception))
        with self.assertRaises(InstrumentError) as ctx:
            decode_reading(encode_reading(0, error=96))
        self.assertIn('error 96', str(ctx.exception))
        self.assertEqual(decode_reading('+9000000000E+01'), 9e10)                # the largest valid value is not an error

    def test_unreadable_text_raises(self):
        for bad in ('', '96921346', '+96921346E+01', 'ABC', '+0096921346E'):
            with self.assertRaises(InstrumentError, msg=bad):
                decode_reading(bad)

    def test_encode_round_trip(self):
        for v in (969_213_460.0, 34_920.0, -37.25, 0.0, 1e-3, 99.9, 4.5e8):
            self.assertAlmostEqual(decode_reading(encode_reading(v)), v, delta=abs(v) * 1e-7)
        self.assertEqual(encode_reading(969_213_460.0), '+0096921346E+01')


class EightNineOhTwo(_NoSleep):
    def test_connect_stores_the_id_reply_and_clears(self):
        bench, src, rx, t = connected_8902a()
        self.assertEqual(rx.id_reply, 'HP8902A')
        self.assertTrue(rx.id_matches)
        self.assertEqual(t.cleared, 1)
        self.assertEqual(rx.address, 14)
        self.assertGreaterEqual(HP8902A.DEFAULT_TIMEOUT, 30.0)
        self.assertGreaterEqual(HP8902A.TUNED_TIMEOUT_S, 30.0)
        self.assertGreaterEqual(max(t.timeouts), 30.0)

    def test_an_empty_id_reply_is_refused(self):
        bench = SimBench()
        t = Sim8902ATransport(bench)
        t.handle = lambda text: '' if text == 'ID' else None
        with self.assertRaises(InstrumentError):
            HP8902A(t).connect()

    def test_a_receiver_that_does_not_answer_id_still_connects_when_it_answers_a_serial_poll(self):
        """Owner bench 2026-10-28: the 8902A does not reply to ID. One short read-only try, a logged warning, a serial poll proves it is there."""
        from drivers.transport import TransportError
        bench = SimBench()
        t = Sim8902ATransport(bench)
        real = t.handle

        def handle(text):
            if text == 'ID':
                raise TransportError('read failed: VI_ERROR_TMO')
            return real(text)
        t.handle = handle
        t.read_stb = lambda: 0
        rx = HP8902A(t)
        rx.connect()
        self.assertEqual(rx.id_reply, '')
        self.assertEqual(t.sent.count('ID'), 1, 'no retry of ID')

    def test_nothing_at_the_address_is_still_an_error(self):
        from drivers.transport import TransportError
        bench = SimBench()
        t = Sim8902ATransport(bench)

        def handle(text):
            raise TransportError('read failed: VI_ERROR_TMO')

        def poll():
            raise TransportError('no device')
        t.handle = handle
        t.read_stb = poll
        with self.assertRaises(InstrumentError):
            HP8902A(t).connect()

    def test_frequency_command_order_and_value(self):
        bench, src, rx, t = connected_8902a(mhz=111.1111)
        f = rx.measure_frequency_hz(111.1111, 10)
        self.assertEqual(t.sent, ['M5', '7.1SP', 'T1', 'T3'])          # bench 2026-10-29 step 4: no tune code
        self.assertAlmostEqual(f, 111_111_100, delta=20)
        self.assertEqual(rf_state(bench)['frequency_hz'], 111_111_100)

    def test_frequency_resolutions_and_the_slow_mode_timeout(self):
        bench, src, rx, t = connected_8902a()
        self.assertEqual(rx.measure_frequency_hz(None, 1000) % 1000, 0)
        self.assertNotIn('AU', t.sent)                                  # no tune code at all (bench 2026-10-29)
        t.timeouts.clear()
        rx.measure_frequency_hz(100.0, 0.1)
        self.assertIn('7.4SP', t.sent)
        self.assertGreaterEqual(max(t.timeouts), 60.0)
        with self.assertRaises(InstrumentError):
            rx.measure_frequency_hz(100.0, 7)

    def test_no_signal_comes_back_as_error_96(self):
        bench, src, rx, t = connected_8902a(rf=False)
        with self.assertRaises(InstrumentError) as ctx:
            rx.measure_frequency_hz(100.0)
        self.assertIn('error 96', str(ctx.exception))

    def test_tuned_level_needs_recal_then_measures(self):
        bench, src, rx, t = connected_8902a(dbm=-30.0)
        with self.assertRaises(RecalRequired):
            rx.tuned_rf_level_dbm(100.0)
        self.assertEqual(t.sent[:5], ['100MZ', 'S4', 'LG', '4.0SP', 'T1'])
        t.sent.clear()
        rx.calibrate_tuned_level(100.0)
        self.assertEqual(t.sent.count('C1'), 1)
        self.assertEqual(t.sent[-1], 'C0')
        t.sent.clear()
        t.timeouts.clear()
        self.assertAlmostEqual(rx.tuned_rf_level_dbm(100.0, 'average'), -30.0, delta=0.05)
        self.assertIn('4.4SP', t.sent)
        self.assertGreaterEqual(max(t.timeouts), 30.0)
        with self.assertRaises(InstrumentError):
            rx.tuned_rf_level_dbm(100.0, 'fast')

    def test_tuned_level_off_tune_and_underdriven(self):
        bench, src, rx, t = connected_8902a(dbm=-30.0)
        rx.calibrate_tuned_level(100.0)
        with self.assertRaises(InstrumentError):
            rx.tuned_rf_level_dbm(105.0)                                       # more than 50 kHz away: no signal
        src.set_level(-130.0, allow_uncal=True)
        with self.assertRaises(InstrumentError) as ctx:
            rx.tuned_rf_level_dbm(100.0)
        self.assertIn('error 19', str(ctx.exception))

    def test_am_depth(self):
        bench, src, rx, t = connected_8902a()
        src.am(30, 'int', 1000)
        self.assertAlmostEqual(rx.measure_am_percent(100.0), 30.05, places=2)
        self.assertEqual(t.sent, ['100MZ', 'M1', 'D1', 'H1', 'L2', 'LN', 'T1', 'T3'])
        t.sent.clear()
        rx.measure_am_percent(100.0, detector=4, hp=2, lp=3)
        self.assertEqual(t.sent[2:5], ['D4', 'H2', 'L3'])
        for bad in ({'detector': 5}, {'hp': 3}, {'lp': 4}):
            with self.assertRaises(InstrumentError):
                rx.measure_am_percent(100.0, **bad)
        src.mod_off()
        self.assertEqual(rx.measure_am_percent(100.0), 0.0)

    def test_fm_deviation_and_deemphasis(self):
        bench, src, rx, t = connected_8902a()
        src.fm(5.0, 'int', 1000)
        self.assertAlmostEqual(rx.measure_fm_deviation_hz(100.0), 5005.0, delta=0.5)
        self.assertEqual(t.sent, ['100MZ', 'M2', 'D1', 'P0', 'H1', 'L2', 'LN', 'T1', 'T3'])
        t.sent.clear()
        flat = rx.measure_fm_deviation_hz(100.0, deemphasis_us=750)
        self.assertEqual(t.sent[3:5], ['P1', 'P5'])
        self.assertLess(flat, 1100.0)                                           # 750 us at 1 kHz: about a factor 5 down
        t.sent.clear()
        rx.measure_fm_deviation_hz(100.0, detector=8)
        self.assertNotIn('P0', t.sent)                                          # true rms forces pre-display on; P0 would not turn it off
        with self.assertRaises(InstrumentError):
            rx.measure_fm_deviation_hz(100.0, deemphasis_us=100)

    def test_distortion_and_rate(self):
        bench, src, rx, t = connected_8902a()
        src.am(30, 'int', 1000)
        self.assertAlmostEqual(rx.measure_distortion(100.0, 1000, 'am'), 0.05, places=3)
        self.assertEqual(t.sent[-6:-1], ['M1', 'S2', 'D5', 'LN', 'T1'])
        with self.assertRaises(InstrumentError):
            rx.measure_distortion(100.0, 400, 'am')                             # the tone is 1 kHz, not 400 Hz
        self.assertEqual(rx.measure_modulation_rate_hz(100.0, 'am'), 1000.0)
        with self.assertRaises(InstrumentError):
            rx.measure_distortion(100.0, 500, 'am')

    def test_time_base_and_firmware(self):
        bench, src, rx, t = connected_8902a()
        self.assertFalse(rx.time_base_is_external())
        t.external_ref = True
        self.assertTrue(rx.time_base_is_external())
        self.assertAlmostEqual(rx.read_special('42.0'), 235.1985, places=3)

    def test_srq_mask_is_read_back(self):
        bench, src, rx, t = connected_8902a()
        self.assertEqual(rx.set_srq_mask(60), 62)
        self.assertEqual(t.sent[-2:], ['22.60SP', '22.64SP'])
        with self.assertRaises(InstrumentError):
            rx.set_srq_mask(64)

    def test_status_byte_flags_a_code_error(self):
        bench, src, rx, t = connected_8902a()
        rx.write('QQ')                                                          # not a code of the language
        with self.assertRaises(InstrumentError) as ctx:
            rx.check_status('test')
        self.assertIn('HP-IB code error', str(ctx.exception))
        self.assertFalse(rx.status()['code_error'])                             # reading the status byte cleared it

    def test_a_failed_write_is_not_retried(self):
        bench, src, rx, t = connected_8902a()
        bench.fail_next = 'M5'
        with self.assertRaises(TransportError):
            rx.measure_frequency_hz(100.0)
        self.assertNotIn('M5', t.sent)
        self.assertNotIn('T3', t.sent)

    def test_recal_is_made_visible_at_connect_and_after_a_reset(self):
        """Bench 2026-10-29: the preset SRQ mask hides RECAL; 22.34SP lets it through (the poll read 96 at each range change)."""
        bench, src, rx, t = connected_8902a()
        self.assertTrue(any(line.rstrip().endswith('>>  22.34SP') for line in rx.log.lines()), rx.log.lines())
        t.sent.clear()
        rx.reset_to_defaults()
        self.assertIn('22.34SP', t.sent)
        self.assertGreater(t.sent.index('22.34SP'), t.sent.index('IP'))

    def test_a_held_setup_is_not_sent_again(self):
        """Bench 2026-10-29 (step 6b): re-sending the tune + S4 at every level re-acquires the signal and loses it below about -110 dBm."""
        bench, src, rx, t = connected_8902a(mhz=120.0, dbm=-13.0)
        from drivers.hp_8902a import RecalRequired
        try:
            rx.tuned_rf_level_dbm(120.0)
        except RecalRequired:
            rx.calibrate_tuned_level(120.0)
            rx.tuned_rf_level_dbm(120.0)
        t.sent.clear()
        rx.tuned_rf_level_dbm(120.0)
        self.assertEqual(t.sent, ['T1', 'T3'])                                   # same setup: only the trigger
        try:
            rx.tuned_rf_level_dbm(244.0)                                         # another frequency: the whole setup again
        except InstrumentError:                                                 # nothing at 244 MHz: only the commands matter here
            pass
        self.assertIn('244MZ', t.sent)
        try:
            rx.measure_frequency_hz(None, 10)                                    # another function in between
        except InstrumentError:
            pass
        t.sent.clear()
        try:
            rx.tuned_rf_level_dbm(244.0)                                         # another function in between: sent again
        except InstrumentError:                                                 # nothing at 244 MHz: only the commands matter here
            pass
        self.assertIn('S4', t.sent)

    def test_power_zero_and_calibration(self):
        bench, src, rx, t = connected_8902a(rf=False)
        self.assertLess(abs(rx.zero_power_sensor()), 3e-6)
        self.assertEqual(t.sent[:4], ['M4', 'LN', 'WT', 'ZR'])
        t.sensor_on_calibrator = True
        t.sent.clear()
        value = rx.calibrate_power_sensor()
        self.assertEqual(t.sent, ['C1T3SC', 'T1', 'T3', 'C0'])                  # the manual's own string, one write; the check reading with the calibrator still on; C0 last
                                                                                 # (M4 LN WT are held from the zero: not sent again)
        self.assertTrue(0.999e-3 <= value <= 1.000e-3)
        t.errors['power_cal_w'] = 0.9e-3
        with self.assertRaises(InstrumentError):
            rx.calibrate_power_sensor()
        t.sensor_on_calibrator = False
        with self.assertRaises(InstrumentError):
            rx.calibrate_power_sensor()

    def test_zero_refuses_a_residual_above_3_microwatts(self):
        bench, src, rx, t = connected_8902a(rf=True, dbm=0.0)
        with self.assertRaises(InstrumentError):
            rx.zero_power_sensor()

    def test_rf_power_dbm_and_a_missing_sensor(self):
        bench, src, rx, t = connected_8902a(dbm=-10.0)
        self.assertAlmostEqual(rx.rf_power_dbm(100.0), -9.98, delta=0.01)
        t.sensor_connected = False
        with self.assertRaises(InstrumentError) as ctx:
            rx.rf_power_dbm(100.0)
        self.assertIn('error 13', str(ctx.exception))

    def test_cal_factor_entry_is_read_back(self):
        bench, src, rx, t = connected_8902a()
        self.assertEqual(rx.enter_reference_cal_factor(98.5), 98.5)
        self.assertIn('37.3SP 98.5 CF', t.sent)
        before = rx.cal_factor_count()
        self.assertEqual(rx.enter_cal_factor(1.0, 99.0), before + 1)
        self.assertIn('37.3SP 1 MZ 99 CF', t.sent)
        self.assertEqual(rx.enter_cal_factor(1.0, 99.5), before + 1)              # same frequency: replaced
        self.assertEqual(t.cf_table, {1.0: 99.5})

    def test_modulation_self_calibration(self):
        bench, src, rx, t = connected_8902a()
        rx.CAL_WAIT_S = 0.0
        self.assertAlmostEqual(rx.calibrate_modulation('am'), 100.02, places=2)
        self.assertEqual(t.sent[:2], ['M1', 'C1'])
        self.assertEqual(t.sent[-1], 'C0')
        t.errors['cal_factor_pct'] = 102.5
        with self.assertRaises(InstrumentError):
            rx.calibrate_modulation('fm')
        self.assertEqual(t.sent[-1], 'C0')                                        # the calibrator is switched off even when the factor is refused
        with self.assertRaises(InstrumentError):
            rx.calibrate_modulation('pm')

    def test_reset_is_ip_and_clean(self):
        bench, src, rx, t = connected_8902a()
        report = rx.reset_to_defaults()
        self.assertTrue(report.ok, report.text())
        self.assertEqual(t.sent[0], 'IP')

    def test_cleanup_never_raises_and_remote_sends_t1(self):
        bench, src, rx, t = connected_8902a()
        rx.remote()
        self.assertEqual(t.sent[-1], 'T1')
        rx.cleanup()


# ======================================================================================================================================================== 8563E
def connected_8563e(rf=True, mhz=100.0, dbm=0.0, **kw):
    bench, t6, _t8902, t8563 = make_rf_bench()
    if kw:
        t8563.__dict__.update(kw)
    src = Fluke6060A(t6).connect()
    src.set_frequency(mhz)
    src.set_level(dbm)
    if rf:
        src.rf('on')
    t8563.timeouts = []
    orig = t8563.set_timeout
    t8563.set_timeout = lambda seconds: (t8563.timeouts.append(seconds), orig(seconds))
    sa = HP8563E(t8563, CommandLog())
    sa.connect()
    t8563.sent.clear()
    return bench, src, sa, t8563


class EightFiveSixThree(_NoSleep):
    def test_connect_and_wrong_model(self):
        bench, src, sa, t = connected_8563e()
        self.assertEqual((sa.idn, sa.address, t.cleared), ('HP8563E', 18, 1))
        bench2 = SimBench()
        t2 = Sim8563ETransport(bench2)
        t2.handle = lambda text: 'HP8560A' if text.startswith('ID?') else None
        with self.assertRaises(InstrumentError):
            HP8563E(t2).connect()

    def test_each_setting_is_sent_once_and_read_back(self):
        bench, src, sa, t = connected_8563e()
        self.assertEqual(sa.set_center_hz(100e6), 100e6)
        self.assertEqual(sa.set_span_hz(1e6), 1e6)
        self.assertEqual(sa.set_rbw_hz(30e3), 30e3)
        self.assertEqual(sa.set_vbw_hz(20e3), 30e3)                                # the analyzer chose 30 kHz: within a factor 2
        self.assertEqual(sa.set_reference_level_dbm(10.0), 10.0)
        self.assertEqual(sa.set_attenuation_db(15), 20)                            # rounded UP to a multiple of 10
        self.assertEqual(t.sent[:4], ['CF 100000000HZ;', 'CF?;', 'SP 1000000HZ;', 'SP?;'])
        self.assertEqual(sa.set_start_hz(10e6), 10e6)
        self.assertEqual(sa.set_stop_hz(600e6), 600e6)
        self.assertEqual(sa.set_marker_threshold(-90.0), -90.0)
        self.assertEqual(sa.set_marker_excursion(6.0), 6.0)
        sa.set_detector('POS')

    def test_values_outside_the_instrument_are_refused_before_anything_is_sent(self):
        bench, src, sa, t = connected_8563e()
        for call in (lambda: sa.set_center_hz(30e9), lambda: sa.set_span_hz(-1), lambda: sa.set_attenuation_db(80), lambda: sa.set_reference_level_dbm(-130.0)):
            with self.assertRaises(InstrumentError):
                call()
        self.assertEqual(t.sent, [])

    def test_a_wrong_read_back_raises_and_the_write_is_sent_once(self):
        bench, src, sa, t = connected_8563e()
        orig = t._statement
        t._statement = lambda stmt: None if stmt.startswith('CF ') else orig(stmt)
        with self.assertRaises(InstrumentError) as ctx:
            sa.set_center_hz(200e6)
        self.assertIn('center frequency', str(ctx.exception))
        self.assertEqual(sum(1 for s in t.sent if s.startswith('CF ')), 1)

    def test_a_failed_write_is_not_retried_and_a_failed_query_is(self):
        bench, src, sa, t = connected_8563e()
        bench.fail_next = 'SP '
        with self.assertRaises(TransportError):
            sa.set_span_hz(2e6)
        self.assertEqual([s for s in t.sent if s.startswith('SP ')], [])
        bench.fail_next = 'CF?'
        self.assertEqual(sa.set_center_hz(100e6), 100e6)                          # CF? is read-only: the retry gets through
        bench.fail_next = 'ERR?'
        with self.assertRaises(TransportError):
            sa.read_errors()                                                      # ERR? clears the list: never retried
        self.assertEqual(t.sent.count('ERR?;'), 0)

    def test_errors_are_named_and_cleared(self):
        bench, src, sa, t = connected_8563e()
        sa.write('FOO;')
        with self.assertRaises(InstrumentError) as ctx:
            sa.check_errors('test')
        self.assertIn('112', str(ctx.exception))
        self.assertIn('unrecognized command', str(ctx.exception))
        self.assertEqual(sa.read_errors(), [])
        sa.write('CF 1000HZ;CF 5MHZ;')                                              # fine
        sa.write('SP 5S;')
        self.assertEqual(sa.read_errors(), [113])

    def test_take_sweep_raises_the_timeout_to_the_sweep_time(self):
        bench, src, sa, t = connected_8563e()
        sa.configure(span_hz=10e3, rbw_hz=100.0)                                   # ST = 2 x span / RBW^2 = 2 s
        t.timeouts.clear()
        self.assertTrue(sa.take_sweep())
        self.assertGreater(max(t.timeouts), sa.sweep_time_s())
        self.assertIn('TS;DONE?;', t.sent)
        self.assertEqual(t.sweeps, 1)

    def test_a_marker_read_without_a_new_sweep_is_stale(self):
        bench, src, sa, t = connected_8563e()
        sa.configure(center_hz=100e6, span_hz=1e6)
        sa.take_sweep()
        f1, _a = sa.marker_to_peak()
        sa.set_center_hz(500e6)                                                     # no TS: the trace is still the old one
        f2, _a = sa.marker_to_peak()
        self.assertEqual(f1, f2)
        sa.take_sweep()
        f3, _a = sa.marker_to_peak()
        self.assertAlmostEqual(f3, 500e6, delta=1e6 / 600 + 1)                      # a new TS and the fifth harmonic is found

    def test_fundamental(self):
        bench, src, sa, t = connected_8563e(mhz=100.0, dbm=0.0)
        fund = sa.measure_fundamental(100e6)
        self.assertAlmostEqual(fund['freq_hz'], 100e6, delta=1e6 / 600)
        self.assertAlmostEqual(fund['level_dbm'], 0.1, places=2)                    # the simulated analyzer adds 0.1 dB
        self.assertEqual(fund['settings']['rbw_hz'], 30e3)
        self.assertIn('MKCF;', t.sent)

    def test_no_carrier_is_an_error(self):
        bench, src, sa, t = connected_8563e(rf=False)
        fund = sa.measure_fundamental(100e6)                                     # NOTE: nothing in the driver rejects a noise-floor "carrier"; the caller checks the level
        self.assertLess(fund['level_dbm'], -100.0)

    def test_harmonic_helper_returns_dbc(self):
        bench, src, sa, t = connected_8563e(mhz=100.0, dbm=0.0)
        out = sa.measure_harmonics(100e6, n_max=5)
        self.assertEqual(len(out['harmonics']), 4)
        for got, want in zip(out['dbc'], (-40.0, -50.0, -60.0, -70.0)):
            self.assertAlmostEqual(got, want, places=2)
        self.assertEqual([h['n'] for h in out['harmonics']], [2, 3, 4, 5])
        self.assertTrue(all(h['found'] for h in out['harmonics']))
        self.assertAlmostEqual(out['fundamental_dbm'], 0.1, places=2)
        self.assertEqual(sum(1 for s in t.sent if s.startswith('CF ') and s.endswith('HZ;')), 5)     # fundamental + 4 harmonics + the re-center after MKCF: counted below
        with_floor = sa.measure_harmonics(100e6, n_max=5, floor_dbm=-72.0)
        self.assertEqual([h['at_floor'] for h in with_floor['harmonics']], [False, False, False, True])

    def test_harmonics_above_the_tuning_range_are_not_measured(self):
        bench, src, sa, t = connected_8563e(mhz=100.0, dbm=0.0)
        rf_state(bench)['frequency_hz'] = 6_000_000_000                         # beyond the 6060A, but the shared bench state can say it
        sa.set_center_hz(6e9)
        out = sa.measure_harmonics(6e9, n_max=5)
        self.assertIsNotNone(out['dbc'][2])                                         # 4 x 6 GHz = 24 GHz
        self.assertIsNone(out['dbc'][3])                                            # 30 GHz is above 26.5 GHz
        self.assertFalse(out['harmonics'][3]['found'])
        with self.assertRaises(InstrumentError):
            sa.measure_harmonics(100e6, n_max=1)

    def test_spur_scan_walks_the_peaks_and_skips_the_harmonics(self):
        bench, src, sa, t = connected_8563e(mhz=100.0, dbm=0.0)
        out = sa.scan_spurs(10e6, 600e6, carrier_hz=100e6, exclude_harmonics=5)
        freqs = sorted(s['freq_hz'] for s in out['spurs'])
        self.assertEqual(len(freqs), 2)
        self.assertAlmostEqual(freqs[0], 50e6, delta=1e6)
        self.assertAlmostEqual(freqs[1], 150e6, delta=1e6)
        self.assertAlmostEqual(out['carrier_dbm'], 0.1, places=2)
        dbc = {round(s['freq_hz'] / 1e6): s['dbc'] for s in out['spurs']}
        self.assertAlmostEqual(dbc[50], -65.0, places=2)
        self.assertAlmostEqual(dbc[150], -72.0, places=2)
        self.assertEqual(out['stopped'], 'marker did not move to a new peak')
        self.assertEqual(out['peaks_visited'], 7)                                    # carrier + 4 harmonics + 2 spurs + the 100 MHz carrier counted once: 7 or 8, pinned
        self.assertIn('MKPK NH;', t.sent)

    def test_spur_scan_stops_at_the_floor_and_at_max_spurs(self):
        bench, src, sa, t = connected_8563e(mhz=100.0, dbm=0.0)
        out = sa.scan_spurs(10e6, 600e6, carrier_hz=100e6, exclude_harmonics=5, floor_dbm=-68.0)
        self.assertEqual([round(s['freq_hz'] / 1e6) for s in out['spurs']], [50])       # the -72 dBc spur is under the marker threshold and never visited
        out = sa.scan_spurs(10e6, 600e6, carrier_hz=100e6, exclude_harmonics=5, max_spurs=1)
        self.assertEqual((out['stopped'], len(out['spurs'])), ('max_spurs', 1))
        with self.assertRaises(InstrumentError):
            sa.scan_spurs(600e6, 10e6)

    def test_delta_to_next_peak_uses_the_manuals_sequence(self):
        bench, src, sa, t = connected_8563e(mhz=100.0, dbm=0.0)
        sa.configure(center_hz=100e6, span_hz=300e6)
        sa.take_sweep()
        t.sent.clear()
        df, da = sa.delta_to_next_peak()
        self.assertEqual(t.sent[:3], ['MKPK HI;', 'MKD;', 'MKPK NH;'])
        self.assertLess(da, 0)

    def test_reset_cleanup_and_outputs(self):
        bench, src, sa, t = connected_8563e()
        report = sa.reset_to_defaults()
        self.assertTrue(report.ok, report.text())
        self.assertEqual(t.sent[0], 'IP;')
        self.assertIn('DONE?;', t.sent)
        sa.cleanup()
        self.assertEqual(t.sent[-1], 'CONTS;')


# ======================================================================================================================================================== bench link
class SharedBench(_NoSleep):
    def test_one_bench_one_signal_for_all_three_instruments(self):
        bench, t6, t8902, t8563 = make_rf_bench()
        gen, rx, sa = Fluke6060A(t6).connect(), HP8902A(t8902).connect(), HP8563E(t8563).connect()
        gen.set_frequency(250.0)
        gen.set_level(-20.0)
        gen.am(30)
        gen.rf('on')
        self.assertAlmostEqual(rx.measure_frequency_hz(250.0), 250e6, delta=20)
        self.assertAlmostEqual(rx.measure_am_percent(250.0), 30.05, places=2)
        self.assertAlmostEqual(sa.measure_fundamental(250e6)['level_dbm'], -19.9, places=2)
        gen.end_point()
        with self.assertRaises(InstrumentError):
            rx.measure_frequency_hz(250.0)
        self.assertEqual(rf_state(bench)['rf_on'], False)

    def test_the_simulators_are_deterministic(self):
        runs = []
        for _ in range(2):
            bench, t6, t8902, t8563 = make_rf_bench()
            gen, rx = Fluke6060A(t6).connect(), HP8902A(t8902).connect()
            gen.set_frequency(100.0)
            gen.set_level(-5.0)
            gen.fm(5.0)
            gen.rf('on')
            runs.append((rx.measure_frequency_hz(100.0), rx.measure_fm_deviation_hz(100.0), t6.sent[:], t8902.sent[:]))
        self.assertEqual(runs[0], runs[1])


# ======================================================================================================================================================== 96270A
class FakeScpi(Transport):
    """A tiny 96270A: INST / UNIT / OUTP / PMET commands, for the added power-meter subset only."""
    name = 'FAKE-96270A'

    def __init__(self, sensor='R&S,NRP40T,100001,1.0', zero='0', reading='-9.87'):
        self.opened = False
        self.sent = []
        self.state = {'INST': 'SINE', 'UNIT': 'DBM', 'PMET:TRIG': 'CONT', 'PMET:AVER': 'AUTO', 'PMET:FREQ': '1E6', 'OUTP': '0', 'POW': '0'}
        self.sensor, self.zero, self.reading = sensor, zero, reading
        self.errors = []
        self._reply = None

    def open(self): self.opened = True
    def close(self): self.opened = False

    def write(self, text):
        self.sent.append(text)
        t = text.strip()
        u = re.sub(r'^PMET\d:', 'PMET:', t.upper())          # the driver sends PMET1: since the bench of 2026-10-29
        self._reply = None
        if u == '*IDN?':
            self._reply = 'Fluke,96270A,1,1'
        elif u in ('*CLS',):
            self.errors = []
        elif u == 'SYST:ERR?':
            self._reply = self.errors.pop(0) if self.errors else '0,"No error"'
        elif u.startswith('INST '):
            self.state['INST'] = {'PMET': 'PMETER', 'SINE': 'SINE'}[u.split()[1]]
            self.state['OUTP'] = '0'
        elif u == 'INST?':
            self._reply = self.state['INST']
        elif u.startswith('UNIT:POW '):
            self.state['UNIT'] = u.split()[1]
        elif u == 'UNIT:POW?':
            self._reply = self.state['UNIT']
        elif u in ('POW:OFFS:STAT 0', 'FREQ:OFFS:STAT 0'):
            self.state[u.split()[0]] = '0'
        elif u == 'POW:OFFS:STAT?' or u == 'FREQ:OFFS:STAT?':
            self._reply = '0'
        elif u == 'OUTP OFF':
            self.state['OUTP'] = '0'
        elif u == 'OUTP?':
            self._reply = self.state['OUTP']
        elif u.startswith('PMET:') and ' ' in u:
            key, value = u.split(None, 1)
            key = {'PMET:TRIG': 'PMET:TRIG', 'PMET:AVER': 'PMET:AVER', 'PMET:FREQ': 'PMET:FREQ'}[key]
            self.state[key] = value
        elif u in ('PMET:TRIG?', 'PMET:AVER?', 'PMET:FREQ?'):
            self._reply = self.state[u[:-1]]
        elif u == 'PMET:IDN?':
            self._reply = self.sensor
        elif u == 'PMET:ZERO?':
            self._reply = self.zero
            if self.zero == '1':
                self.errors.append('-221,"Settings conflict: sensor not zeroed"')
        elif u == 'PMET:READ?':
            self._reply = self.reading
        else:
            raise TransportError(f'fake 96270A: unknown command {text!r}')

    def read(self):
        if self._reply is None:
            raise TransportError('no reply')
        reply, self._reply = self._reply, None
        return reply


ORIGINAL_RF_COMMANDS = {
    'status.clear': '*CLS', 'inst.set': 'INST SINE', 'inst.query': 'INST?', 'unit.set': 'UNIT:POW DBM', 'unit.query': 'UNIT:POW?', 'poffs.set': 'POW:OFFS:STAT 0',
    'poffs.query': 'POW:OFFS:STAT?', 'foffs.set': 'FREQ:OFFS:STAT 0', 'foffs.query': 'FREQ:OFFS:STAT?', 'freq.level': 'FREQ {f:.12g};:POW {p:.3f}', 'freq.query': 'FREQ?',
    'level.query': 'POW?', 'outp.on': 'OUTP ON', 'outp.off': 'OUTP OFF', 'outp.query': 'OUTP?', 'err.query': 'SYST:ERR?', 'reset': '*RST', 'opc.query': '*OPC?'}


class PowerMeterMode(_NoSleep):
    def make(self, **kw):
        t = FakeScpi(**kw)
        drv = Fluke96270A(t, CommandLog())
        drv.connect()
        t.sent.clear()
        return t, drv

    def test_the_existing_rf_commands_are_unchanged(self):
        for key, template in ORIGINAL_RF_COMMANDS.items():
            self.assertEqual(RF_COMMANDS[key].template, template, key)
        self.assertEqual(sorted(k for k in RF_COMMANDS if k not in ORIGINAL_RF_COMMANDS), sorted(reference_instruments.PMETER_COMMANDS))
        self.assertEqual(cmdreg.lint_registry(RF_COMMANDS), [])

    def test_the_new_commands_have_pages_and_the_unverified_ones_are_listed(self):
        for key, cmd in reference_instruments.PMETER_COMMANDS.items():
            self.assertTrue(cmd.ref and 'p. ' in cmd.ref, key)
        self.assertEqual(unverified(reference_instruments.PMETER_COMMANDS), UNVERIFIED_96270A_NEW)
        self.assertIn('NRP40T', reference_instruments.PMETER_COMMANDS['pm.idn'].description)
        self.assertIn('UNVERIFIED', reference_instruments.PMETER_COMMANDS['pm.idn'].description)
        self.assertEqual(reference_instruments.PMETER_COMMANDS['pm.zero'].risk, 'locked')

    def test_select_power_meter_sequence_and_read_back(self):
        t, drv = self.make()
        ident = drv.select_power_meter(1e9, 'AUTO', single=True)
        self.assertEqual(ident, 'R&S,NRP40T,100001,1.0')
        self.assertEqual(t.sent[:3], ['INST PMET', 'INST?', 'PMET1:TRIG SING'])          # no UNIT:POW in power-meter mode (bench 2026-10-29)
        self.assertIn('PMET1:FREQ 1000000000', t.sent)
        self.assertEqual(t.state['INST'], 'PMETER')
        self.assertEqual(t.state['PMET:AVER'], 'AUTO')
        t2, drv2 = self.make()
        drv2.select_power_meter(5e8, '16', single=False)
        self.assertIn('PMET1:AVER 16', t2.sent)
        self.assertIn('PMET1:TRIG CONT', t2.sent)

    def test_no_sensor_is_refused(self):
        t, drv = self.make(sensor='NONE, NONE, NONE, NONE')
        with self.assertRaises(InstrumentError):
            drv.select_power_meter(1e9)

    def test_a_refused_read_back_raises(self):
        t, drv = self.make()
        orig = t.write

        def stubborn(text):
            if text.startswith('PMET1:AVER '):
                t.sent.append(text)
                t._reply = None
                return
            orig(text)
        t.write = stubborn
        with self.assertRaises(InstrumentError):
            drv.select_power_meter(1e9, '16')
        self.assertEqual(sum(1 for s in t.sent if s.startswith('PMET1:AVER ')), 1)

    def test_zero_is_asked_once_and_a_failure_names_the_error(self):
        t, drv = self.make()
        drv.zero()
        self.assertEqual(t.sent, ['PMET1:ZERO?'])
        t2, drv2 = self.make(zero='1')
        with self.assertRaises(InstrumentError) as ctx:
            drv2.zero()
        self.assertIn('error queue', str(ctx.exception))
        self.assertEqual(t2.sent.count('PMET1:ZERO?'), 1)

    def test_read_dbm(self):
        t, drv = self.make(reading='-9.87E+00')
        self.assertEqual(drv.read_dbm(), -9.87)
        for bad in ('9.91E+37', 'nan', 'abc', '+2.5E+02', '-2.5E+02'):
            t.reading = bad
            with self.assertRaises(InstrumentError, msg=bad):
                drv.read_dbm()

    def test_back_to_the_source(self):
        t, drv = self.make()
        drv.select_power_meter(1e9)
        t.sent.clear()
        drv.select_sine()
        self.assertEqual(t.sent[0], 'INST SINE')
        self.assertEqual(t.state['INST'], 'SINE')
        self.assertEqual(t.state['OUTP'], '0')


if __name__ == '__main__':
    unittest.main()
