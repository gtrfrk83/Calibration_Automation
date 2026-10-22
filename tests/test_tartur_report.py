"""Optional TAR / TUR columns on the exports: off (default) is identical to before, on adds the columns and footer."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TK = ('tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.filedialog', 'tkinter.font', 'tkinter.scrolledtext')
try:
    import tkinter  # noqa: F401
except Exception:
    for _n in _TK:
        sys.modules.setdefault(_n, mock.MagicMock())

import report_pdf  # noqa: E402

try:
    import reportlab  # noqa: F401
    HAVE_RL = True
except Exception:
    HAVE_RL = False

FIXED = datetime(2026, 1, 2, 3, 4)


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED


def sample_rows():
    return [
        report_pdf.cert_row('10 V range', 10, 9.9990, 10.0010, 'V', reading=10.0002, section='DC Volts', uncertainty='12 µV/V'),
        report_pdf.cert_row('100 V range', 100, 99.99, 100.01, 'V', reading=100.02, failed=True, section='DC Volts', uncertainty='20 µV/V'),
        report_pdf.cert_row('1 kΩ', 1000, 999.5, 1000.5, 'ohm', reading=1000.1, section='Resistance'),
    ]


def build(module, path, rows, **kw):
    import reportlab.rl_config as rc
    rc.invariant = 1
    with mock.patch.object(module, 'datetime', _Clock):
        return module.write_calibration_pdf(path, rows, header=[('Instrument', 'Test DMM'), ('Instrument ID', 'A1')], **kw)


def pdf_text(path):
    return subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout


class Settings(unittest.TestCase):
    def test_default_false_on_first_run(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(report_pdf.remembered_show_tar_tur(Path(d) / 'none.json'))

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'sub' / 'x.json'
            self.assertTrue(report_pdf.remember_show_tar_tur(True, p))
            self.assertTrue(report_pdf.remembered_show_tar_tur(p))
            report_pdf.remember_show_tar_tur(False, p)
            self.assertFalse(report_pdf.remembered_show_tar_tur(p))

    def test_corrupt_file_is_false(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x.json'
            p.write_text('{not json')
            self.assertFalse(report_pdf.remembered_show_tar_tur(p))

    def test_unwritable_path_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            blocker = Path(d) / 'file'
            blocker.write_text('x')
            self.assertFalse(report_pdf.remember_show_tar_tur(True, blocker / 'child' / 'x.json'))
            self.assertFalse(report_pdf.remembered_show_tar_tur(blocker / 'child' / 'x.json'))

    def test_default_path_under_home(self):
        self.assertEqual(report_pdf.settings_path().parent.name, '.calibration_suite')


class Helpers(unittest.TestCase):
    def test_off_returns_same_rows(self):
        rows = sample_rows()
        self.assertIs(report_pdf.apply_tar_tur(rows, False, [{'TAR': '4:1'}] * 3), rows)
        self.assertNotIn('TAR', rows[0])

    def test_on_merges_without_mutating(self):
        rows = sample_rows()
        out = report_pdf.apply_tar_tur(rows, True, [{'TAR': '4.0:1', 'TUR': '3.1:1'}, None, {'TAR': '', 'TUR': '2:1'}])
        self.assertEqual((out[0]['TAR'], out[0]['TUR']), ('4.0:1', '3.1:1'))
        self.assertEqual((out[1]['TAR'], out[1]['TUR']), ('', ''))
        self.assertNotIn('TAR', rows[0])
        out2 = report_pdf.apply_tar_tur(rows, True, lambda r: {'TAR': r['UOM']})
        self.assertEqual(out2[0]['TAR'], 'V')

    def test_csv_helpers(self):
        self.assertEqual(report_pdf.csv_columns(False), [])
        self.assertEqual(report_pdf.csv_cells(False, {'TAR': '4:1'}), [])
        self.assertEqual(report_pdf.csv_columns(True), ['TAR', 'TUR'])
        self.assertEqual(report_pdf.csv_cells(True, {'TAR': '4:1', 'TUR': '3:1'}), ['4:1', '3:1'])
        self.assertEqual(report_pdf.csv_cells(True, None), ['', ''])
        row = ['a', 'b']
        self.assertEqual(row + report_pdf.csv_cells(False, {'TAR': 'x'}), ['a', 'b'])
        self.assertTrue(report_pdf.csv_show_tar_tur(True))
        self.assertFalse(report_pdf.csv_show_tar_tur(False))

    def test_definition_never_empty(self):
        self.assertIn('TAR', report_pdf.tar_tur_definition())


@unittest.skipUnless(HAVE_RL and Path('/usr/bin/pdftotext').exists(), 'reportlab / pdftotext not available')
class Pdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        # golden: report_pdf exactly as on origin/main
        src = subprocess.run(['git', 'show', 'origin/main:report_pdf.py'], cwd=ROOT, capture_output=True, text=True)
        cls.golden = None
        if src.returncode == 0:
            gp = Path(cls.tmp.name) / 'report_pdf_main.py'
            gp.write_text(src.stdout, encoding='utf-8')
            spec = importlib.util.spec_from_file_location('report_pdf_main', gp)
            cls.golden = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.golden)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def path(self, name):
        return Path(self.tmp.name) / name

    def with_fields(self):
        return report_pdf.apply_tar_tur(sample_rows(), True, [{'TAR': '4.0:1', 'TUR': '3.1:1'}, {'TAR': '4.0:1', 'TUR': ''}, None])

    def test_off_identical_to_main(self):
        if self.golden is None:
            self.skipTest('origin/main not available')
        a, b = self.path('old.pdf'), self.path('new.pdf')
        build(self.golden, a, sample_rows())
        build(report_pdf, b, sample_rows())
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_off_ignores_row_fields_and_footer(self):
        if self.golden is None:
            self.skipTest('origin/main not available')
        a, b = self.path('old2.pdf'), self.path('new2.pdf')
        build(self.golden, a, sample_rows())
        build(report_pdf, b, self.with_fields(), details={'show_tar_tur': False})      # fields present but flag off
        self.assertEqual(a.read_bytes(), b.read_bytes())
        b2 = self.path('new2b.pdf')
        build(report_pdf, b2, self.with_fields(), show_tar_tur=False, details={'show_tar_tur': True})   # keyword forces off
        self.assertEqual(a.read_bytes(), b2.read_bytes())

    def test_on_without_values_is_unchanged(self):
        if self.golden is None:
            self.skipTest('origin/main not available')
        a, b = self.path('old3.pdf'), self.path('new3.pdf')
        build(self.golden, a, sample_rows())
        build(report_pdf, b, sample_rows(), details={'show_tar_tur': True})              # no row has TAR / TUR: no empty columns
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_on_shows_columns_and_footer(self):
        p = self.path('on.pdf')
        build(report_pdf, p, self.with_fields(), details={'show_tar_tur': True})
        text = pdf_text(p)
        self.assertIn('TAR', text)
        self.assertIn('TUR', text)
        self.assertIn('4.0:1', text)
        self.assertIn('3.1:1', text)
        self.assertIn(report_pdf.tar_tur_definition()[:40], ' '.join(text.split()))
        self.assertIn('N/A', text)                       # blank TUR / unfielded row follow the Uncertainty rule
        self.assertIn('Calibration Data', text)

    def test_keyword_turns_on(self):
        p = self.path('kw.pdf')
        build(report_pdf, p, self.with_fields(), show_tar_tur=True)
        self.assertIn('3.1:1', pdf_text(p))

    def test_demo_marking_kept_when_on(self):
        p = self.path('demo.pdf')
        build(report_pdf, p, self.with_fields(), details={'show_tar_tur': True}, demo=True)
        text = pdf_text(p)
        self.assertIn('DEMO DATA', text)
        self.assertIn('3.1:1', text)


if __name__ == '__main__':
    unittest.main()
