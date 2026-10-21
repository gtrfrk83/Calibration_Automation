"""Rule: DC volts / DC amps outputs always carry an explicit 0 Hz (see NOTES.md standing rules)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DMM_ENGINES = ['handheld_dmm.py', 'truevolt_verification.py', 'dacq_verification.py',
               'Procedures/Agilent_34401A.py', 'Procedures/Fluke_8846A_Verification.py']


class DcZeroHz(unittest.TestCase):
    def test_engines_pass_dc_flag(self):
        for name in DMM_ENGINES:
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertRegex(text, r'set_output_volts\([^)]*dc=', name)
            self.assertRegex(text, r'set_output_amps\([^)]*dc=', name)

    def test_driver_sends_0hz_for_dc(self):
        from drivers.fluke_5560a import COMMANDS
        self.assertEqual(COMMANDS['out.volts.dc'].template, 'OUT {volts:.9g}V,0Hz')
        self.assertEqual(COMMANDS['out.amps.dc'].template, 'OUT {amps:.9g}A,0Hz')


if __name__ == '__main__':
    unittest.main()
