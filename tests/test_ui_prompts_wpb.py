"""WP-B (bench DMM engines): the Tk-level prompt sequences of Truevolt, DACQ, Keithley 2000, 34401A and 8846A equal the fixtures recorded from the UNPORTED code
(tests/golden_ui/ui_prompts_<key>.json).  The ScriptedUiPort side is tests/test_ui_prompts.py::Port, which runs every engine listed in tests/ui_ported.txt.
Rewrite a fixture only for an INTENDED prompt change: python -m tests.ui_prompt_capture --update <key>."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import ui_prompt_capture as C  # noqa: E402


class TkLevelWpB(unittest.TestCase):
    def check(self, name):
        want = json.loads(C.fixture_path(name).read_text(encoding='utf-8'))
        got = json.loads(json.dumps(C.capture(name, C.TkLevelHarness)))
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], f'{name}: scenario {scenario}')

    def test_truevolt(self):
        self.check('truevolt')

    def test_dacq(self):
        self.check('dacq')

    def test_keithley2000(self):
        self.check('k2000')

    def test_agilent34401a(self):
        self.check('a34401a')

    def test_fluke8846a(self):
        self.check('f8846a')


if __name__ == '__main__':
    unittest.main()
