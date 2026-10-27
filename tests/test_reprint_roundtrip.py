"""Asset History 'Regenerate PDF': snapshot -> PDF round trip against the engines' real export code on the simulated benches.

For the handheld / user-datasheet engine (handheld_dmm.App via dsb_runtime.DsbApp on the simulated calibrators), the Truevolt 34470A engine and
the TDS2000C scope engine: the original PDF is produced by the engine's own export_pdf() (so the Asset History event and the snapshot are written by
the production code path), then regenerated from the saved record.  The reprint must have the same pages and the same text, and each page's content
must be the original's unchanged (no footer note).  Clock pinned, reportlab invariant mode.

File name sorts AFTER test_beta on purpose: it installs tests/_tk_stub.py (no tkinter here), which would change test_beta if loaded earlier.
Run:  python -m unittest tests.test_reprint_roundtrip
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import reprint_harness as R  # noqa: E402
import dsb_run_harness as H  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import test_dsb_runtime_bench as B  # noqa: E402  (spec_of / cal_io helpers only)
import labregistry  # noqa: E402
from tests import _tk_stub as _boot  # noqa: E402  (test-only stand-ins for the removed Tk modules)
_boot.install()  # noqa: E402
import report_dialog  # noqa: E402
import report_pdf  # noqa: E402
import report_snapshot as rs  # noqa: E402

try:
    import reportlab  # noqa: F401
    import pypdf  # noqa: F401
    HAVE = subprocess.run(['pdftotext', '-v'], capture_output=True).returncode in (0, 99)
except Exception:
    HAVE = False

NOTE = None                                                       # a reprint of the saved record carries no note


def regenerate(rid, out):
    return rs.regenerate(rid, choose_path=lambda name, original: str(out), confirm_overwrite=lambda p, o: False)


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        ctx = R.registry()
        self.db = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def check(self, original, rid, name):
        self.assertIsNotNone(rid, 'the export wrote an Asset History event')
        self.assertEqual(rs.load(rid).status, rs.OK, 'the engine export saved a report snapshot')
        out = self.dir / f'{name}_reprint.pdf'
        res = regenerate(rid, out)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.kind, rs.SNAPSHOT)
        self.assertEqual(R.differences(original, out, NOTE), [], f'{name}: reprint differs from the original')
        self.assertNotIn('Reprinted', R.pdf_text(out))
        return out

    def test_truevolt_engine(self):
        pdf = self.dir / 'tv.pdf'
        R.truevolt_export(pdf, details={'show_tar_tur': report_pdf.TarTur(True, False)})
        text = R.pdf_text(pdf)
        self.assertIn('TAR', text)
        self.assertIn('AS LEFT: PASS', text)
        out = self.check(pdf, R.last_run_id(), 'truevolt')
        self.assertIn('TAR', R.pdf_text(out))
        self.assertNotIn('TUR (test uncertainty', R.pdf_text(out), 'only the TAR column was ticked: the TAR / TUR toggle state is restored exactly')
        stamps = rs.load(R.last_run_id()).data['stamps']
        self.assertIn('truevolt_verification', stamps['code_sha256'])
        self.assertEqual(stamps['spec']['file'], 'keysight_34470a_pv.json')
        self.assertTrue(stamps['spec']['file_sha256'])
        self.assertTrue(stamps['as_left_present'])

    def test_truevolt_toggle_off_and_both_on(self):
        for n, tt in enumerate((False, True)):
            pdf = self.dir / f'tv{n}.pdf'
            R.truevolt_export(pdf, details={'show_tar_tur': tt})
            out = self.check(pdf, R.last_run_id(), f'truevolt{n}')
            self.assertEqual('TUR' in R.pdf_text(out).split('RESULT')[1].split('Zero offset')[0], tt)

    def test_scope_engine_tds2000c(self):
        pdf = self.dir / 'tds.pdf'
        R.tds_export(pdf, details={'show_tar_tur': True})
        out = self.check(pdf, R.last_run_id(), 'tds')
        self.assertIn('CH1 DC gain', R.pdf_text(out))

    def test_reprint_does_not_add_history_events(self):
        pdf = self.dir / 'tv.pdf'
        R.truevolt_export(pdf)
        before = len(labregistry.runs_for('A-100'))
        regenerate(R.last_run_id(), self.dir / 'again.pdf')
        self.assertEqual(len(labregistry.runs_for('A-100')), before)

    def test_difference_check_is_not_vacuous(self):
        a, b = self.dir / 'a.pdf', self.dir / 'b.pdf'
        R.truevolt_export(a)
        R.tds_export(b, details={'technician': 'x'})
        self.assertTrue(R.differences(a, b, NOTE), 'two different reports must be reported as different')


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class HandheldEngine(unittest.TestCase):
    """handheld_dmm.App through dsb_runtime.DsbApp on the simulated 5560A / 5522A, typed readings: the real run, judging, rows and export_pdf()."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.h = H.Harness().start()
        self.addCleanup(self.h.stop)
        ctx = R.registry()
        self.db = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def export(self, app, out, details):
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': dict(details)), \
                mock.patch.object(B.rt.hh.filedialog, 'asksaveasfilename', lambda **k: str(out)):
            app.export_pdf()

    @staticmethod
    def short_spec():
        spec = B.spec_of(fx.dmm_34461a_like())
        spec['steps'] = spec['steps'][::7]              # every 7th step of the example datasheet: a mix of functions, a faster simulated run
        return spec

    def test_handheld_run_round_trip(self):
        app = self.h.make_app(self.short_spec(), io=B.cal_io())
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertFalse(app.any_synthetic())
        pdf = self.dir / 'hh.pdf'
        self.export(app, pdf, dict(R.DETAILS, show_tar_tur=report_pdf.TarTur(False, True)))
        rid = R.last_run_id('A-100')
        self.assertIsNotNone(rid)
        snap = rs.load(rid)
        self.assertEqual(snap.status, rs.OK)
        d = snap.data
        self.assertEqual(d['details']['technician'], 'T. Tech')
        self.assertEqual(d['details']['standards'][0]['serial'], 'S5560')
        self.assertEqual(d['details']['show_tar_tur'], {'__tar_tur__': [False, True]})
        self.assertIn('dsb_runtime', d['stamps']['code_sha256'])
        self.assertIn('handheld_dmm', d['stamps']['code_sha256'])
        self.assertEqual(d['stamps']['spec']['datasheet']['title'], '34461A example datasheet')
        out = self.dir / 'hh_reprint.pdf'
        res = regenerate(rid, out)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(R.differences(pdf, out, NOTE), [])

    def test_demo_run_is_never_snapshotted(self):
        app = self.h.make_app(self.short_spec(), demo=True)
        for p in app.points:
            app._record_demo(p)
        self.assertTrue(app.any_synthetic())
        pdf = self.dir / 'demo.pdf'
        self.export(app, pdf, R.DETAILS)
        self.assertTrue(pdf.exists())
        self.assertIn('NOT CALIBRATION EVIDENCE', R.pdf_text(pdf))
        self.assertEqual(labregistry.runs_for('A-100'), [], 'demo reports are not in the Asset History')
        with rs._db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM report_snapshots').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
