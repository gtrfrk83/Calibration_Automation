"""A DEMO report's page-footer title must not print over the centred red 'DEMO DATA - NOT CALIBRATION EVIDENCE' line.
Non-demo footers are untouched (byte-identical)."""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import reportlab  # noqa: F401
    HAVE_RL = True
except Exception:
    HAVE_RL = False
HAVE_PDFTOTEXT = Path('/usr/bin/pdftotext').exists()

LONG = 'Datasheet Builder Very Long Procedure Title For A Handheld Multimeter Performance Verification With Extra Words'
ROWS = [dict(Section='DC Voltage', Description='6 V range', Nominal='1.000 V', **{'Tolerance -': '0.99', 'Tolerance +': '1.01'}, UOM='V', **{'As Found': '1.0001'})]


@unittest.skipUnless(HAVE_RL, 'reportlab not available')
class Helper(unittest.TestCase):
    def cut(self, text):
        import report_pdf
        return report_pdf.demo_footer_left(text, 'Helvetica', 7, 36.0, 612.0, 'Helvetica-Bold', 8)

    def test_short_text_unchanged(self):
        self.assertEqual(self.cut('Instrument ID: A-1   |   Fluke 77'), 'Instrument ID: A-1   |   Fluke 77')

    def test_long_text_is_cut_with_ellipsis_and_clears_the_demo_line(self):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        import report_pdf
        out = self.cut('Instrument ID: A-1   |   ' + LONG)
        self.assertTrue(out.endswith('...'))
        self.assertTrue(out.startswith('Instrument ID: A-1'))
        demo_left = 306.0 - stringWidth(report_pdf.DEMO_FOOTER_TEXT, 'Helvetica-Bold', 8) / 2
        self.assertLess(36.0 + stringWidth(out, 'Helvetica', 7), demo_left)

    def test_always_ends_before_demo_line_for_every_length(self):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        import report_pdf
        demo_left = 306.0 - stringWidth(report_pdf.DEMO_FOOTER_TEXT, 'Helvetica-Bold', 8) / 2
        for n in range(0, 140):
            out = self.cut('Instrument ID: A-1   |   ' + 'W' * n)
            self.assertLess(36.0 + stringWidth(out, 'Helvetica', 7), demo_left, n)


@unittest.skipUnless(HAVE_RL and HAVE_PDFTOTEXT, 'reportlab / pdftotext not available')
class Pdf(unittest.TestCase):
    def render(self, title, demo):
        import report_pdf
        d = Path(self.tmp.name)
        path = d / f'{"demo" if demo else "real"}_{abs(hash(title))}.pdf'
        report_pdf.write_calibration_pdf(path, [dict(r) for r in ROWS], header=[('Instrument ID', 'A-TEST')], title=title, demo=demo, record_history=False)
        return path

    def footer_words(self, pdf):
        out = subprocess.run(['pdftotext', '-f', '1', '-l', '1', '-bbox', str(pdf), '-'], capture_output=True, text=True).stdout
        return [(float(a), float(b), float(c), t) for a, b, c, t in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="[\d.]+">(.*?)</word>', out) if float(b) > 740]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_long_demo_title_does_not_overlap_demo_line(self):
        words = self.footer_words(self.render(LONG, True))
        demo_start = min(w[0] for w in words if w[3] == 'DEMO')
        demo_end = max(w[2] for w in words if w[3] == 'EVIDENCE')
        left = [w for w in words if w[2] <= demo_start + 0.01 or (w[0] < demo_start and w[2] > demo_start)]
        self.assertTrue(left)
        self.assertLess(max(w[2] for w in left), demo_start)           # the cut title ends before the red line starts
        self.assertTrue(all(w[0] > demo_end for w in words if w[0] > demo_start and w[3] not in ('DEMO', 'DATA', '-', 'NOT', 'CALIBRATION', 'EVIDENCE')))
        text = ' '.join(w[3] for w in sorted(words))
        self.assertIn('...', text)
        self.assertNotIn('Words', text)                   # the tail of the title is gone

    def test_fluke_115_title_demo(self):
        words = self.footer_words(self.render('Fluke 115 Performance Verification', True))
        demo_start = min(w[0] for w in words if w[3] == 'DEMO')
        titled = [w for w in words if w[0] < demo_start]
        self.assertLess(max(w[2] for w in titled), demo_start)

    def test_short_demo_title_unchanged(self):
        text = ' '.join(w[3] for w in sorted(self.footer_words(self.render('Fluke 77', True))))
        self.assertIn('Fluke 77', text)
        self.assertNotIn('...', text)

    def test_non_demo_long_title_footer_unchanged(self):
        text = ' '.join(w[3] for w in sorted(self.footer_words(self.render(LONG, False))))
        self.assertIn('Words', text)
        self.assertNotIn('...', text)
        self.assertNotIn('DEMO', text)


if __name__ == '__main__':
    unittest.main()
