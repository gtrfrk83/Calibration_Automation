"""WP-G prompt sequences (fgen, MDO4000C, TDS2000C): the Tk calls of each engine, recorded on the simulated bench, equal the fixture recorded from the UNPORTED code
(tests/golden_ui/ui_prompts_<engine>.json).  Holds before and after the port: TkUiPort makes the same calls.  The ScriptedUiPort run of the same scenarios is
tests/test_ui_prompts.py::Port (it covers every engine listed in tests/ui_ported.txt)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import test_ui_prompts as P  # noqa: E402
from tests import ui_prompt_capture as C  # noqa: E402


class TkLevelWpG(unittest.TestCase):
    def check(self, name):
        want, got = P.recorded(name), P.canon(C.capture(name, C.TkLevelHarness))
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], f'{name}: scenario {scenario}')

    def test_fgen(self):
        self.check('fgen')

    def test_mdo4000c(self):
        self.check('mdo4000c')

    def test_tds2000c(self):
        self.check('tds2000c')


if __name__ == '__main__':
    unittest.main()
