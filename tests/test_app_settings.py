"""app_settings: the per-user settings store behind File > Settings."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app_settings as A


class Store(unittest.TestCase):
    def setUp(self):
        home = Path(tempfile.mkdtemp())
        p = mock.patch.object(Path, 'home', classmethod(lambda cls: home))
        p.start()
        self.addCleanup(p.stop)

    def test_defaults_are_on_so_nothing_changes_until_a_person_switches_something_off(self):
        self.assertTrue(A.manual_override_on() and A.hand_sections_on())

    def test_saved_values_are_kept_and_unknown_keys_ignored(self):
        A.set_many({A.MANUAL_OVERRIDE: False, 'nonsense': 1})
        self.assertFalse(A.manual_override_on())
        self.assertTrue(A.hand_sections_on())
        self.assertIsNone(A.get('nonsense'))
        A.set_many({A.MANUAL_OVERRIDE: True})
        self.assertTrue(A.manual_override_on())

    def test_a_damaged_file_means_defaults(self):
        path = Path.home() / '.calibration_suite' / 'settings.json'
        path.parent.mkdir(parents=True)
        path.write_text('{not json', encoding='utf-8')
        self.assertTrue(A.manual_override_on())

    def test_every_option_has_text_and_a_boolean_default(self):
        for key, group, label, why, default in A.OPTIONS:
            self.assertTrue(key and group and label and why)
            self.assertIsInstance(default, bool)


class Addresses(unittest.TestCase):
    def setUp(self):
        home = Path(tempfile.mkdtemp())
        p = mock.patch.object(Path, 'home', classmethod(lambda cls: home))
        p.start()
        self.addCleanup(p.stop)
        import ui_theme_core as core
        self.core = core

    def test_defaults_prefill_a_procedure_that_never_saved_an_address(self):
        A.set_addresses({'5560A': 'COM9', '5522A': 'GPIB0::4::INSTR', '3458A': 'GPIB0::22::INSTR', 'junk': 'x'}, first=False)
        s = self.core.Settings('SomeProcedure')
        self.assertEqual(s.get('addr_3458A', ''), 'GPIB0::22::INSTR')
        self.assertEqual(s.get('addr_5790B', ''), '')                    # no default for it: the procedure's own default
        self.assertEqual(s.get('cal_addr', 'COM1'), 'COM1')              # no calibrator chosen yet and two defaults: never guess the calibrator
        s.set('cal_mode', 'Fluke 5522A  (automatic output)')
        self.assertEqual(s.get('cal_addr', 'COM1'), 'GPIB0::4::INSTR')   # the chosen calibrator picks the address
        self.assertNotIn('junk', A.addresses())

    def test_a_procedures_own_saved_address_wins_unless_the_settings_come_first(self):
        A.set_addresses({'3458A': 'GPIB0::22::INSTR'}, first=False)
        s = self.core.Settings('P')
        s.set('addr_3458A', 'GPIB0::9::INSTR')
        self.assertEqual(s.get('addr_3458A', ''), 'GPIB0::9::INSTR')
        A.set_addresses({'3458A': 'GPIB0::22::INSTR'}, first=True)
        self.assertEqual(s.get('addr_3458A', ''), 'GPIB0::22::INSTR')

    def test_the_instrument_under_test_and_other_stores_are_never_touched(self):
        A.set_addresses({'5522A': 'COM9'}, first=True)
        s = self.core.Settings('P')
        self.assertEqual(s.get('dmm_addr', 'USB0::x'), 'USB0::x')
        self.assertEqual(s.get('ir_addr', 'COM5'), 'COM5')


class MoreDefaults(unittest.TestCase):
    def setUp(self):
        home = Path(tempfile.mkdtemp())
        self.home = home
        p = mock.patch.object(Path, 'home', classmethod(lambda cls: home))
        p.start()
        self.addCleanup(p.stop)
        import ui_theme_core as core
        self.core = core

    def test_the_other_standard_boxes(self):
        A.set_addresses({'5790B': 'GPIB0::8::INSTR', '53132A': 'GPIB0::3::INSTR', '96270A': 'GPIB0::5::INSTR', '33250A': 'GPIB0::10::INSTR'}, first=False)
        fg = self.core.Settings('fgen_33250A')
        self.assertEqual(fg.get('std', ''), 'GPIB0::8::INSTR')
        self.assertEqual(fg.get('counter', ''), 'GPIB0::3::INSTR')
        mdo = self.core.Settings('MDO4000C')
        self.assertEqual((mdo.get('rf1', ''), mdo.get('rf2', ''), mdo.get('gen', '')), ('GPIB0::5::INSTR', 'GPIB0::5::INSTR', 'GPIB0::10::INSTR'))
        self.assertEqual(mdo.get('std', 'x'), 'x', "'std' is the 5790B of the generator procedures only")
        k = self.core.Settings('Keysight53220A')
        self.assertEqual((k.get('rf_addr', ''), k.get('gen_addr', '')), ('GPIB0::5::INSTR', 'GPIB0::10::INSTR'))
        self.assertEqual(k.get('ctr_addr', 'UUT'), 'UUT', 'the instrument under test is never defaulted')

    def test_two_calibrators_and_no_choice_leaves_the_procedures_own_default(self):
        A.set_addresses({'5560A': 'COM9', '5522A': 'COM4'}, first=False)
        s = self.core.Settings('P')
        self.assertEqual(s.get('cal_addr', 'COM1'), 'COM1')
        s.set('cal_model', 'Fluke 5522A')
        self.assertEqual(s.get('cal_addr', 'COM1'), 'COM4')

    def test_calibrator_baud_default(self):
        s = self.core.Settings('P')
        self.assertEqual(s.get('cal_baud', '9600'), '9600')
        A.set_many({A.CAL_BAUD: '19200'})
        self.assertEqual(s.get('cal_baud', '9600'), '19200')

    def test_report_tar_and_tur_are_off_by_default_and_follow_the_settings(self):
        import report_pdf
        t = report_pdf.remembered_show_tar_tur()
        self.assertEqual((t.tar, t.tur), (False, False))
        report_pdf.remember_show_tar_tur(True)                          # a report was made with both ticked
        t = report_pdf.remembered_show_tar_tur()
        self.assertEqual((t.tar, t.tur), (False, False), 'the next report starts from the defaults, not from the last choice')
        A.set_many({A.REPORT_TUR: True})
        t = report_pdf.remembered_show_tar_tur()
        self.assertEqual((t.tar, t.tur), (False, True))
        A.set_many({A.REPORT_LAST: True})
        t = report_pdf.remembered_show_tar_tur()
        self.assertEqual((t.tar, t.tur), (True, True), 'the older behaviour: the last choice')

    def test_report_folder_is_used_only_when_it_exists(self):
        self.assertEqual(A.report_folder(), '')
        A.set_many({A.REPORT_FOLDER: str(self.home)})
        self.assertEqual(A.report_folder(), str(self.home))
        A.set_many({A.REPORT_FOLDER: str(self.home / 'gone')})
        self.assertEqual(A.report_folder(), '')
