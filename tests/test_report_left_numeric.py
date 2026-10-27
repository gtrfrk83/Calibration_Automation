"""'As left data as numerical' checkbox next to TAR / TUR (owner request 2026-10-27): details['left_numeric'] copies every As Found reading into As Left on the PDF.
Run:  python -m unittest tests.test_report_left_numeric"""
import subprocess
import tempfile
import unittest
from pathlib import Path

import report_pdf


def rows():
    return [report_pdf.cert_row('DC 1 V', 1.0, 0.99, 1.01, 'V', reading=1.0004, uncertainty='0.0001'),
            report_pdf.cert_row('DC 10 V', 10.0, 9.9, 10.1, 'V', reading=10.2, failed=True),
            report_pdf.cert_row('untested', 100.0, 99.0, 101.0, 'V')]


class Copy(unittest.TestCase):
    def test_as_found_copied_to_as_left_with_the_oot_flag(self):
        out, copied = report_pdf.apply_left_numeric(rows(), {'left_numeric': True})
        self.assertTrue(copied)
        self.assertEqual(out[0]['As Left'], out[0]['As Found']); self.assertNotEqual(out[0]['As Left'], 'Same')
        self.assertFalse(out[0]['As Left OOT'])
        self.assertEqual(out[1]['As Left'], out[1]['As Found']); self.assertTrue(out[1]['As Left OOT'])
        self.assertEqual(out[2]['As Left'], '')                           # untested row stays empty

    def test_off_changes_nothing_and_the_input_is_not_modified(self):
        r = rows()
        out, copied = report_pdf.apply_left_numeric(r, {})
        self.assertFalse(copied); self.assertIs(out, r)
        report_pdf.apply_left_numeric(r, {'left_numeric': True})
        self.assertEqual(r[0]['As Left'], 'Same')

    def test_a_real_as_left_reading_is_kept(self):
        r = rows(); r[1]['As Left'] = '10.01'
        out, _c = report_pdf.apply_left_numeric(r, {'left_numeric': True})
        self.assertEqual(out[1]['As Left'], '10.01')

    def test_choice_is_remembered_next_to_tar_tur_without_clobbering_it(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 't.json'
            self.assertFalse(report_pdf.remembered_left_numeric(f))
            report_pdf.remember_show_tar_tur(report_pdf.TarTur(True, False), f)
            report_pdf.remember_left_numeric(True, f)
            self.assertTrue(report_pdf.remembered_left_numeric(f))
            self.assertEqual(report_pdf.remembered_show_tar_tur(f), report_pdf.TarTur(True, False))
            report_pdf.remember_show_tar_tur(report_pdf.TarTur(False, True), f)
            self.assertTrue(report_pdf.remembered_left_numeric(f))          # kept when TAR / TUR is saved again


class Pdf(unittest.TestCase):
    def text(self, details):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'r.pdf'
            report_pdf.write_calibration_pdf(str(p), rows(), header=[('Instrument ID', 'A-1')], details=details, demo=True, record_history=False)
            return subprocess.run(['pdftotext', '-layout', str(p), '-'], capture_output=True, text=True).stdout

    def test_pdf_shows_same_by_default_and_numbers_when_checked(self):
        off = self.text({})
        self.assertIn('Same', off)
        on = self.text({'left_numeric': True})
        self.assertNotIn('Same', on)
        self.assertIn('no adjustment made', on)
        self.assertIn('1.0004', on.replace(' ', ''))


if __name__ == '__main__':
    unittest.main()
