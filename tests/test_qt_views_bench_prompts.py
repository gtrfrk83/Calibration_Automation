"""QT-G1a, engine level: the REAL bench verification engines (Truevolt, DACQ, Keithley 2000, 34401A, Fluke 8846A, Fluke 8808A, 34410A / 34411A) run on their simulated
benches through the Qt window code (`<name>_view_qt`) in an offscreen window, with the real QtUiPort for windows / threads / timers and the scripted operator of
tests/ui_prompt_capture*.py answering the prompts, and the prompt sequence of every scenario must equal the one recorded from the Tk build (tests/golden_ui/ui_prompts_<engine>.json):
same prompts, same order, same answers consumed.  Also: the Tk-level recorders underneath stay empty (no prompt bypasses the port).

Skipped without PySide6.  Run one engine:  python -m unittest tests.test_qt_views_bench_prompts.Prompts.test_truevolt   (each takes about 30-40 s; run them as separate processes)."""
import json
import os
import sys
import unittest
from unittest import mock
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    import qt_bench_harness as QH


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Prompts(unittest.TestCase):
    def check(self, name):
        C = QH.C
        fakes = {}
        if name == 'f8846a':                                               # only the Excel export's dependency check is skipped: the prompts before / after it are the point
            try:
                import openpyxl  # noqa: F401
            except ImportError:
                fakes = {n: mock.MagicMock() for n in ('openpyxl', 'openpyxl.styles', 'openpyxl.utils', 'openpyxl.worksheet', 'openpyxl.worksheet.page')}
        with mock.patch.dict(sys.modules, fakes):
            got = json.loads(json.dumps(C.SCENARIOS[name](lambda answers=None: QH.QtHarness(answers))))
        want = json.loads(C.fixture_path(name).read_text(encoding='utf-8'))
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], f'{name}: scenario {scenario}')

    def test_truevolt(self):
        self.check('truevolt')

    def test_dacq(self):
        self.check('dacq')

    def test_k2000(self):
        self.check('k2000')

    def test_a34401a(self):
        self.check('a34401a')

    def test_f8846a(self):
        self.check('f8846a')

    def test_f8808a(self):
        self.check('f8808a')

    def test_a34410a(self):
        self.check('a34410a')


if __name__ == '__main__':
    unittest.main()
