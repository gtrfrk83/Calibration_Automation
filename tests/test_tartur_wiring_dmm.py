"""TAR / TUR wiring in the multimeter engines (truevolt, dacq, 34401A, 8846A, handheld family).

* each engine's export path still calls the report helpers (fails if a wire is cut);
* toggle off: PDF is byte-identical to origin/tartur-integration (same pinned clock), toggle on adds the columns;
* the limits and calibrator model fed to tartur are the ones the row's Tolerance / Uncertainty cells were built from.
Engines are driven headlessly through tests/dmm_export_harness.py (tkinter stubbed, engines' own demo readings)."""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import dmm_export_harness  # noqa: E402

dmm_export_harness.stub_tk()          # tkinter is not needed by the report layer; stub it where it is not installed

try:
    import reportlab  # noqa: F401
    HAVE_RL = True
except Exception:
    HAVE_RL = False
HAVE_PDFTOTEXT = Path('/usr/bin/pdftotext').exists()

POINT_ROW_ENGINES = {'truevolt_verification.py': "'5560A'", 'dacq_verification.py': 'self.cal_key', 'Procedures/Agilent_34401A.py': "'5560A'",
                     'Procedures/Fluke_8846A_Verification.py': "'5560A'"}


def src(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


class SourceWiring(unittest.TestCase):
    """Reading-only guard: the export code must keep routing through the helpers, with the calibrator model of the Uncertainty column."""

    def test_pdf_path_applies_fields_before_writing(self):
        for rel, model in POINT_ROW_ENGINES.items():
            s = src(rel)
            body = s[s.index('def export_pdf'):]
            self.assertIn('apply_tar_tur', body, rel)
            self.assertLess(body.index('apply_tar_tur'), body.index('write_calibration_pdf'), rel)
            self.assertIn(f'tartur_wiring.point_fields(p,{model})'.replace(',', ',' if 'Procedures' in rel or rel.startswith('truevolt') else ', '), body, rel)
            # the model passed to point_row (Uncertainty column) is the model passed to the fields
            self.assertIn('standard=' + model, s[s.index('def certificate_rows_and_points'):], rel)

    def test_handheld_pdf_path(self):
        s = src('handheld_dmm.py')
        body = s[s.index('def export_pdf'):]
        self.assertIn('apply_tar_tur', body)
        self.assertLess(body.index('apply_tar_tur'), body.index('write_calibration_pdf'))
        self.assertIn('certificate_fields', body)
        fields = s[s.index('def certificate_fields'):s.index('def export_pdf')]
        self.assertIn('tartur.row_fields', fields)
        self.assertIn('standard=self.calibrator_model()', fields)
        self.assertIn('standard=self.calibrator_model()', s[s.index('def certificate_row('):s.index('def certificate_rows(')])

    def test_helpers_exist(self):
        import report_pdf
        self.assertTrue(callable(report_pdf.apply_tar_tur))
        for name in ('csv_show_tar_tur', 'csv_columns', 'csv_cells'):
            self.assertFalse(hasattr(report_pdf, name), name)


class Limits(unittest.TestCase):
    def test_point_limits_match_printed_tolerances(self):
        import report_pdf
        import tartur_wiring
        pts = [dict(kind='DCV', nominal=10.0, range=10.0, unit='V', error=0.0004, frequency=None),
               dict(kind='DCV', nominal=-10.0, range=10.0, unit='V', low=-10.001, high=-9.999, frequency=None),
               dict(kind='DCV', nominal=0.0, range=1.0, unit='V', error=1e-5, frequency=None, zero_offset=True, source='none')]
        for p in pts:
            low, high = tartur_wiring.point_limits(p)
            row = report_pdf.point_row(p, p['nominal'], False)
            ref = report_pdf.cert_row('x', p['nominal'], low, high, p['unit'])
            self.assertEqual((row['Tolerance -'], row['Tolerance +']), (ref['Tolerance -'], ref['Tolerance +']))

    def test_fields_are_blank_for_zero_offset_and_never_raise(self):
        import tartur_wiring
        z = dict(kind='DCV', nominal=0.0, range=1.0, unit='V', error=1e-5, frequency=None, zero_offset=True, source='none')
        self.assertEqual(tartur_wiring.point_fields(z, '5560A'), dict(TAR='', TUR=''))
        self.assertEqual(tartur_wiring.point_fields({}, '5560A'), dict(TAR='', TUR=''))

    def test_tur_uses_the_printed_uncertainty(self):
        """TUR = half the printed tolerance / the Uncertainty cell value (same calibrator model)."""
        import report_pdf
        import tartur
        import tartur_wiring
        p = dict(kind='DCV', nominal=10.0, range=10.0, unit='V', error=0.0004, frequency=None)
        unc = report_pdf.point_uncertainty(p, '5560A')
        m = re.match(r'([\d.]+)\s*(µ|m)?V', unc)
        self.assertIsNotNone(m, unc)
        u = float(m.group(1)) * {None: 1, 'µ': 1e-6, 'm': 1e-3}[m.group(2)]
        want = tartur.format_ratio(0.0004 / u)
        self.assertEqual(tartur_wiring.point_fields(p, '5560A')['TUR'], want)


def run_dump(root, out, mode):
    r = subprocess.run([sys.executable, str(ROOT / 'tests' / 'dmm_export_harness.py'), str(root), str(out), mode], capture_output=True, text=True, cwd=str(root))
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return r.stdout


@unittest.skipUnless(HAVE_RL and HAVE_PDFTOTEXT, 'reportlab / pdftotext not available')
class Exports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.off, cls.none, cls.on = t / 'off', t / 'none', t / 'on'
        run_dump(ROOT, cls.off, 'off')
        run_dump(ROOT, cls.none, 'none')
        run_dump(ROOT, cls.on, 'on')
        cls.base = None
        g = subprocess.run(['git', 'rev-parse', '--verify', '-q', 'origin/tartur-integration'], cwd=ROOT, capture_output=True, text=True)
        if g.returncode == 0:
            cls.base_root = t / 'base_tree'
            cls.base_root.mkdir()
            tar = subprocess.run(['git', 'archive', 'origin/tartur-integration'], cwd=ROOT, capture_output=True)
            subprocess.run(['tar', '-x', '-C', str(cls.base_root)], input=tar.stdout, check=True)
            cls.base = t / 'base'
            run_dump(cls.base_root, cls.base, 'off')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def files(self, d, pattern):
        return sorted(p.name for p in Path(d).glob(pattern))

    def test_all_engines_exported(self):
        self.assertEqual(len(self.files(self.off, '*.pdf')), 9)

    def test_off_and_absent_key_are_identical(self):
        for n in self.files(self.off, '*.pdf'):
            self.assertEqual((self.off / n).read_bytes(), (self.none / n).read_bytes(), n)

    def test_off_identical_to_baseline(self):
        if self.base is None:
            self.skipTest('origin/tartur-integration not available')
        names = self.files(self.base, '*.pdf')
        self.assertEqual(len(names), 9)
        for n in names:
            if n == 'handheld_Fluke_87V.pdf':
                self.check_87v_rows_only(n)          # the 87V points 1-48 / 1-49 (peak Min/Max square wave) and 1-50 / 1-51 (degC) changed on purpose
                continue
            if n == 'handheld_Fluke_287.pdf':
                self.check_temperature_rows_only(n)  # the 287 temperature rows (3-1 .. 3-3) now print a thermocouple-simulation Uncertainty (temperature uncertainty branch)
                continue
            self.assertEqual((self.base / n).read_bytes(), (self.off / n).read_bytes(), n)

    def check_87v_rows_only(self, n):
        import difflib
        txt = lambda d: subprocess.run(['pdftotext', '-layout', str(d / n), '-'], capture_output=True, text=True).stdout.splitlines()
        changed = [l[2:] for l in difflib.ndiff(txt(self.base), txt(self.off)) if l[:2] in ('- ', '+ ')]
        self.assertTrue(changed)
        for l in changed:
            self.assertRegex(l, r'Min / Max|^\s*6 V range|Type K range', l)
        self.assertLessEqual(len(changed), 14)

    def check_temperature_rows_only(self, n):
        """Only the Temperature rows differ from the baseline, and only in the Uncertainty cell (N/A before, 'x.xx degC' now)."""
        import difflib
        txt = lambda d: subprocess.run(['pdftotext', '-layout', str(d / n), '-'], capture_output=True, text=True).stdout.splitlines()
        changed = [l for l in difflib.ndiff(txt(self.base), txt(self.off)) if l[:2] in ('- ', '+ ')]
        self.assertEqual(len(changed), 6, changed)
        for l in changed:
            self.assertRegex(l[2:], r'^\s*Temperature\s', l)
            self.assertRegex(l[2:], r'N/A\s*$' if l[0] == '-' else r'\d+(\.\d+)? \u00b0C\s*$', l)

    def test_on_pdf_has_columns_and_values(self):
        for n in self.files(self.on, '*.pdf'):
            text = subprocess.run(['pdftotext', '-layout', str(self.on / n), '-'], capture_output=True, text=True).stdout
            self.assertRegex(text, r'Uncertainty\s+TAR\s+TUR', n)
            self.assertRegex(text, r'\d+\.\d:1', n)
            self.assertIn('TAR (test accuracy ratio)', ' '.join(text.split()), n)
            self.assertRegex(text, r'(?i)demo', n)                       # demo marking survives
            off = subprocess.run(['pdftotext', '-layout', str(self.off / n), '-'], capture_output=True, text=True).stdout
            self.assertNotIn('TUR', off, n)


if __name__ == '__main__':
    unittest.main()
