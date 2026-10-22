"""Stage 5: 'Procedure modifications' block, tolerance header line, run_overrides persistence, byte-identical unmodified reports."""
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import devmode  # noqa: E402
import procmods as pm  # noqa: E402
import report_pdf  # noqa: E402
from test_procmods import Base  # noqa: E402
from test_tartur_report import _Clock, build, pdf_text, sample_rows, HAVE_RL  # noqa: E402


def _baseline_module(tmp):
    """report_pdf exactly as committed before this stage (git show of the parent of the first commit touching modifications)."""
    src = subprocess.run(['git', 'show', 'origin/procmods-integration:report_pdf.py'], cwd=ROOT, capture_output=True, text=True)
    if src.returncode:
        return None
    p = Path(tmp) / 'report_pdf_baseline.py'
    p.write_text(src.stdout, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('report_pdf_baseline', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@unittest.skipUnless(HAVE_RL, 'reportlab not installed')
class ReportMods(Base):
    def setUp(self):
        super().setUp()
        self.reg = mock.patch('labregistry.record_run')
        self.reg.start()
        self.addCleanup(self.reg.stop)

    def _limit_set(self):
        p = self.points[3]
        self.store.add('limit', pm.point_key(p), {'mode': 'error', 'error': p['error'] * 2}, 'model', 'customer spec', model='34465A',
                       point=p, session=self.session, author='me')
        self.add_nplc()
        return pm.resolve('34465A', None, store=self.store)

    def test_unmodified_is_byte_identical(self):
        base = _baseline_module(self.dir)
        if base is None:
            self.skipTest('git baseline unavailable')
        old, a, b, c = (self.dir / n for n in ('old.pdf', 'a.pdf', 'b.pdf', 'c.pdf'))
        build(base, old, sample_rows())
        build(report_pdf, a, sample_rows())
        build(report_pdf, b, sample_rows(), modifications=[])
        build(report_pdf, c, sample_rows(), modifications=pm.resolve('34465A', None, store=self.store))       # empty OverrideSet
        for f in (a, b, c):
            self.assertEqual(old.read_bytes(), f.read_bytes())
        self.assertNotIn('Procedure modifications', pdf_text(a))

    def test_block_and_header_line(self):
        o = self._limit_set()
        out = self.dir / 'm.pdf'
        build(report_pdf, out, sample_rows(), modifications=o)
        t = ' '.join(pdf_text(out).split())
        self.assertIn('Procedure modifications', t)
        self.assertIn("modified from the manufacturer's specification", t)
        self.assertIn('customer spec', t)
        self.assertIn('VOLT:DC:NPLC2', t)
        self.assertNotEqual(out.read_bytes(), self._plain().read_bytes())

    def test_non_limit_override_has_no_tolerance_line(self):
        self.add_nplc()
        out = self.dir / 'n.pdf'
        build(report_pdf, out, sample_rows(), modifications=pm.resolve('34465A', None, store=self.store))
        t = ' '.join(pdf_text(out).split())
        self.assertIn('Procedure modifications', t)
        self.assertNotIn("modified from the manufacturer's specification", t)

    def _plain(self):
        p = self.dir / 'plain.pdf'
        build(report_pdf, p, sample_rows())
        return p

    def test_run_overrides_in_lab_registry_and_for_report(self):
        o = self._limit_set()
        self.assertTrue(pm.record_run_snapshot('R1', o, store=self.store))
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute('select count(*) from run_overrides').fetchone()[0], 1)
        con.close()
        lines = pm.modifications_for_report('R1', store=self.store)
        self.assertEqual(sorted(m['kind'] for m in lines), ['command', 'limit'])
        self.assertTrue(all(m['reason'] and m['date'] and m['version'] for m in lines))
        self.assertEqual(pm.modifications_for_report('nope', store=self.store), [])
        self.assertFalse(pm.record_run_snapshot('R2', o, demo=True, store=self.store))
        self.assertEqual(pm.modifications_for_report('R2', store=self.store), [])
        out = self.dir / 'r.pdf'
        build(report_pdf, out, sample_rows(), modifications=lines)
        self.assertIn('Procedure modifications', pdf_text(out))

    def test_demo_keeps_watermark_and_records_nothing(self):
        o = self._limit_set()
        out = self.dir / 'd.pdf'
        build(report_pdf, out, sample_rows(), modifications=o, demo=True)
        self.assertIn('DEMO DATA - NOT CALIBRATION EVIDENCE', pdf_text(out))
        self.assertFalse(pm.record_run_snapshot('D1', o, demo=True, store=self.store))

    def test_calibration_procedures_db_untouched(self):
        import inspect
        self.assertNotIn('calibration_procedures', inspect.getsource(pm.modifications_for_report) + inspect.getsource(report_pdf._mod_lines))


if __name__ == '__main__':
    unittest.main()
