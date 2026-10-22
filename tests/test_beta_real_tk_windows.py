"""The new windows on a REAL Tk (point editor window, Edit point button, Procedures list Mark verified / Unlock, Datasheet Builder grid, Asset History
Regenerate PDF), driven with real events in a subprocess (tests/real_tk_checks.py), in the light and the dark theme.

Skipped when this Python has no tkinter or there is no display (and no xvfb-run to make one).  The subprocess gets its own data folder, so nothing
of the person's is touched.  Run:  python -m unittest tests.test_beta_real_tk_windows
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _has_tk():
    try:
        r = subprocess.run([sys.executable, '-c', 'import tkinter'], capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _command(theme):
    cmd = [sys.executable, str(ROOT / 'tests' / 'real_tk_checks.py'), theme]
    if not os.environ.get('DISPLAY') and sys.platform != 'win32':
        xvfb = shutil.which('xvfb-run')
        if not xvfb:
            return None
        cmd = [xvfb, '-a', '-s', '-screen 0 1600x1000x24'] + cmd
    return cmd


@unittest.skipUnless(_has_tk(), 'tkinter is not available in this Python')
class RealTkWindows(unittest.TestCase):
    def run_theme(self, theme):
        cmd = _command(theme)
        if cmd is None:
            self.skipTest('no display and no xvfb-run')
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        env = dict(os.environ, CALSUITE_DATA=os.path.join(home, 'data'), HOME=home, USERPROFILE=home)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + '\n' + r.stderr[-3000:])
        self.assertIn('ALL OK', r.stdout)

    def test_light_theme(self):
        self.run_theme('light')

    def test_dark_theme(self):
        self.run_theme('dark')
