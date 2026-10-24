"""WP-G: ui_port.call_from_worker through the fgen engine on a real Tk 9 under Xvfb (tests/real_tk_wpg_fgen.py in a subprocess; skipped without tkinter / a display)."""
import glob
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def real_python():
    cands = sorted(glob.glob(str(Path.home() / '.local/share/uv/python/*/bin/python3')), reverse=True) + [sys.executable]
    for c in cands:
        try:
            if subprocess.run([c, '-c', 'import tkinter'], capture_output=True, timeout=60).returncode == 0:
                return c
        except (OSError, subprocess.SubprocessError):
            pass
    return None


class CallFromWorkerOnRealTk(unittest.TestCase):
    def run_one(self, scenario):
        py = real_python()
        if py is None:
            self.skipTest('no Python with tkinter')
        cmd = [py, str(ROOT / 'tests' / 'real_tk_wpg_fgen.py'), scenario]
        if not os.environ.get('DISPLAY'):
            xvfb = shutil.which('xvfb-run')
            if not xvfb:
                self.skipTest('no display and no xvfb-run')
            cmd = [xvfb, '-a', '-s', '-screen 0 1280x800x24'] + cmd
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + '\n' + r.stderr[-3000:])
        self.assertIn('ALL OK', r.stdout)

    def test_typed_reading_answered(self):
        self.run_one('answer')

    def test_typed_reading_cancelled(self):
        self.run_one('cancel')

    def test_exception_in_the_dialog_gives_the_worker_none(self):
        self.run_one('raise')


if __name__ == '__main__':
    unittest.main()
