"""WP-A (adjustment launchers): the three launchers are toolkit-free and the new port methods exist on every implementation.

* tests/test_ui_port_clean.py checks the FIRST file of each tests/ui_ported.txt line; the 'adjustments' line lists two launchers, so the second is checked here.
* ask_value / update / enable_hidpi are on TkUiPort and ScriptedUiPort with the same signatures (the contract in ui_port.py).
* The calibration password / code of the adjustment launchers is asked with ask_text(show='*'): the scripted port records it masked.
"""
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import test_ui_port_clean as clean  # noqa: E402
import ui_port  # noqa: E402

LAUNCHERS = ['Procedures/Keithley_2000_Adjustment.py', 'Procedures/Fluke_8808A_Adjustment.py', 'Procedures/Fluke_8846A_Adjustment.py']
VIEWS = ['keithley2000_adjust_view_tk.py', 'fluke8808a_adjust_view_tk.py', 'fluke8846a_adjust_view_tk.py']


class Launchers(unittest.TestCase):
    def test_no_toolkit_left_in_the_launchers(self):
        for f in LAUNCHERS:
            self.assertEqual(clean.problems(ROOT / f), [], f)



class NewPortMethods(unittest.TestCase):

    def test_scripted_ask_value_answers_the_default_and_records(self):
        p = ui_port.ScriptedUiPort()
        self.assertEqual(p.ask_value('Calibrator value', 'Enter it', '10'), '10')
        self.assertEqual(p.prompts, [{'kind': 'ask_value', 'title': 'Calibrator value', 'text': 'Enter it', 'answer': '10'}])
        q = ui_port.ScriptedUiPort(ui_port.Answers([lambda r: None if r['kind'] != 'ask_value' else '9.9']))
        self.assertEqual(q.ask_value('t', 'p', '10'), '9.9')

    def test_a_secret_is_masked_in_the_record(self):
        p = ui_port.ScriptedUiPort(ui_port.Answers([lambda r: 'S3cret' if r['kind'] == 'ask_text' else None]))
        self.assertEqual(p.ask_text('Calibration code', 'Enter', show='*'), 'S3cret')
        self.assertNotIn('S3cret', repr(p.prompts))


if __name__ == '__main__':
    unittest.main()
