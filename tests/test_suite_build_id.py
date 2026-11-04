"""suite_info.build_id: the commit a copy was built from, shown in every window title (owner, 2026-11-04). `python -m unittest tests.test_suite_build_id`"""
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suite_info  # noqa: E402


class BuildId(unittest.TestCase):
    def setUp(self):
        suite_info.build_id.cache_clear()

    def tearDown(self):
        suite_info.build_id.cache_clear()

    def test_a_filled_build_file_is_shown_in_the_title(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'BUILD.txt').write_text('abc1234 2026-11-04\n', encoding='utf-8')
            with mock.patch.object(suite_info, '_HERE', Path(t)):
                self.assertEqual(suite_info.build_id(), 'abc1234 2026-11-04')
                self.assertEqual(suite_info.window_title('Fluke 6060A'), f'Calibration Suite  |  Fluke 6060A  |  {suite_info.full_version()} · abc1234 2026-11-04')

    def test_no_build_file_and_no_git_shows_the_version_alone(self):
        with tempfile.TemporaryDirectory() as t, mock.patch.object(suite_info, '_HERE', Path(t)), \
                mock.patch.object(suite_info.subprocess, 'run', side_effect=OSError('no git')):
            self.assertEqual(suite_info.build_id(), '')
            self.assertEqual(suite_info.title_version(), suite_info.full_version())

    def test_git_archive_fills_the_build_file(self):
        """The build zip is made with git archive: .gitattributes export-subst must turn BUILD.txt into '<short sha> <date>'."""
        if subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True).returncode != 0:
            self.skipTest('not a git checkout')
        attrs = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        self.assertIn('BUILD.txt export-subst', attrs)
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / 'b.zip'
            r = subprocess.run(['git', 'archive', '--format=zip', '-o', str(out), 'HEAD', 'BUILD.txt', '.gitattributes'], cwd=ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                self.skipTest('BUILD.txt is not committed yet: ' + r.stderr.strip())
            text = zipfile.ZipFile(out).read('BUILD.txt').decode().strip()
            sha = subprocess.run(['git', 'log', '-1', '--format=%h'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
            self.assertTrue(text.startswith(sha + ' 20'), text)


if __name__ == '__main__':
    unittest.main()
