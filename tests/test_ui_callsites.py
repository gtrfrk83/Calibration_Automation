"""Prompt call sites per file (tools/ui_callsites.py): a port of an engine from Tk to ui_port must leave every manifest identical.

The 18 files of the Qt-migration inventory plus the shared helpers whose dialogs those engines reach.  Recorded on the unported code (branch qt-phase1-foundation,
before any port); a file that is ported later must still match its entry: same prompts, same title / text expressions, same order inside each function.
If a prompt is changed ON PURPOSE (a different job), review it and rewrite the fixture:

    python -m tests.test_ui_callsites --update
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

import ui_callsites  # noqa: E402

FIXTURE = ROOT / 'tests' / 'golden_ui' / 'callsites.json'

ENGINES = [
    'handheld_dmm.py', 'surprise.py', 'procspec.py', 'iflex_option.py', 'truevolt_verification.py', 'fgen_verification.py', 'dacq_verification.py',
    'agilent34410a_verification.py', 'mdo4000c_verification.py', 'fluke8808a_verification.py', 'keithley2000_verification.py', 'tds2000c_verification.py',
    'Procedures/WaveSurfer_WS4104HD.py', 'Procedures/Fluke_8846A_Verification.py', 'Procedures/Fluke_8846A_Adjustment.py', 'Procedures/Agilent_34401A.py',
    'Procedures/Keithley_2000_Adjustment.py', 'Procedures/Fluke_8808A_Adjustment.py',
]
HELPERS = ['datamode.py', 'reset_startup.py', 'procmods_engine.py', 'manual_override.py', 'run_queue_engine.py', 'procmods_ui.py', 'hookups.py', 'ui_shell.py', 'ui_theme.py',
           'run_queue_ui.py', 'report_dialog.py', 'labregistry_ui.py']


def current():
    return {f: ui_callsites.manifest(ROOT / f) for f in ENGINES + HELPERS}


class CallSites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recorded = json.loads(FIXTURE.read_text(encoding='utf-8'))
        cls.now = current()

    def test_every_file_is_recorded(self):
        self.assertEqual(sorted(self.recorded), sorted(ENGINES + HELPERS))

    def test_prompts_unchanged(self):
        bad = [f for f in ENGINES + HELPERS if self.now[f] != self.recorded[f]]
        self.assertEqual(bad, [], 'prompt call sites changed (kind, title / text expression or order); if intended: python -m tests.test_ui_callsites --update')

    def test_file_diff_is_readable(self):
        for f in ENGINES + HELPERS:
            if self.now[f] != self.recorded[f]:
                a, b = self.recorded[f], self.now[f]
                for i, (x, y) in enumerate(zip(a, b)):
                    if x != y:
                        self.fail(f'{f}: call site {i} differs\n  recorded {x}\n  now      {y}')
                self.fail(f'{f}: {len(a)} call sites recorded, {len(b)} now')


if __name__ == '__main__':
    if sys.argv[1:] == ['--update']:
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(current(), indent=1, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
        print('wrote', FIXTURE)
    else:
        unittest.main()
