"""Operator-prompt sequences (tests/ui_prompt_capture.py): what each engine shows, in order, with the answers it consumed.

* TkLevel: the Tk calls (message boxes, file dialogs, confirm_steps, report details) of the engine, recorded on the simulated bench, equal the fixture recorded from
  the UNPORTED code (tests/golden_ui/ui_prompts_<engine>.json).  Holds before and after a port: TkUiPort makes the same calls.
* Port: for an engine listed in PORTED, the same scenarios through ui_port.ScriptedUiPort give the same sequence, and nothing reaches a Tk dialog function.

Rewrite a fixture only for an INTENDED prompt change: python -m tests.ui_prompt_capture --update <engine>.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import ui_ported  # noqa: E402
from tests import ui_prompt_capture as C  # noqa: E402

PORTED = ui_ported.keys()                  # engines whose Tk calls all go through ui_port: tests/ui_ported.txt (add your line when you port one, after recording its fixture)


def recorded(name):
    return json.loads(C.fixture_path(name).read_text(encoding='utf-8'))


def canon(obj):
    return json.loads(json.dumps(obj))


class TkLevel(unittest.TestCase):
    def check(self, name):
        want, got = recorded(name), canon(C.capture(name, C.TkLevelHarness))
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], f'{name}: scenario {scenario}')

    def test_a34410a(self):
        self.check('a34410a')

    def test_f8808a(self):
        self.check('f8808a')

    def test_handheld_families(self):
        self.check('handheld')

    def test_adjustment_launchers(self):
        self.check('adjustments')

    def test_handheld_other_families(self):
        self.check('handheld_families')

    def test_shared_helpers(self):                      # WP-S: run queue, manual override, data mode, note, reset (recorded on the unported helpers)
        self.check('shared')

    # ---- WP-W (WaveSurfer 4104HD; recorded on the unported engine) -- append-only block
    def test_wavesurfer(self):
        self.check('wavesurfer')

    def test_adjustment_launcher_8846a(self):
        self.check('adj8846a')


class Port(unittest.TestCase):
    def test_every_ported_engine_prompts_only_through_the_port(self):
        for name in PORTED:
            want, got = recorded(name), canon(C.capture(name, C.PortHarness))      # the scenario asserts that no Tk-level prompt was recorded
            self.assertEqual(sorted(got), sorted(want))
            for scenario in want:
                if scenario in C.TK_LEVEL_ONLY.get(name, ()):
                    continue                       # reaches a shared helper that still prompts through Tk (see ui_prompt_capture.TK_LEVEL_ONLY)
                self.assertEqual(got[scenario], want[scenario], f'{name}: scenario {scenario}')


if __name__ == '__main__':
    unittest.main()
