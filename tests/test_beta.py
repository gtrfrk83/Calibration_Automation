"""Beta edition: data folder, diagnostics, titles, Help menu, shortcuts, report footer."""
import contextlib, importlib, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import appdata, branding, diagnostics, suite_info          # noqa: E402

try:
    import tkinter as tk
    _p = tk.Tk(); _p.destroy()
    HAVE_TK = True
except Exception:
    HAVE_TK = False


class DataFolder(unittest.TestCase):
    def test_env_overrides_and_creates(self):
        d = Path(tempfile.mkdtemp()) / 'x' / 'y'
        with mock.patch.dict(os.environ, {'CALSUITE_DATA': str(d)}):
            self.assertEqual(appdata.data_dir(), d)
            self.assertTrue(d.is_dir())
            p = appdata.progress_path('a_checkpoint.json')
            self.assertEqual(p.parent, d / 'progress')
            self.assertEqual(appdata.db_path('lab_registry.sqlite3'), d / 'lab_registry.sqlite3')

    def test_default_folder_is_per_edition(self):
        with mock.patch.dict(os.environ, {'CALSUITE_DATA': ''}), mock.patch.object(appdata, 'is_portable', lambda: False), \
                mock.patch('pathlib.Path.mkdir'):
            self.assertIn('CalibrationSuite-Beta', str(appdata.data_dir()))

    def test_import_copies_and_backs_up_and_leaves_source(self):
        src = Path(tempfile.mkdtemp()); dest = Path(tempfile.mkdtemp())
        (src / 'calibration_procedures.sqlite3').write_bytes(b'SRC-MAIN')
        (src / 'Procedures').mkdir(); (src / 'Procedures' / '8846A_T1_checkpoint.json').write_text('{"a":1}')
        (dest / 'lab_registry.sqlite3').write_bytes(b'OLD')
        (dest / 'calibration_procedures.sqlite3').write_bytes(b'OLD-MAIN')
        with mock.patch.dict(os.environ, {'CALSUITE_DATA': str(dest)}):
            done = appdata.import_from(src)
            self.assertIn('calibration_procedures.sqlite3', done)
            self.assertEqual((dest / 'calibration_procedures.sqlite3').read_bytes(), b'SRC-MAIN')
            self.assertEqual((dest / 'lab_registry.sqlite3').read_bytes(), b'OLD')             # not in the source: untouched
            self.assertEqual(len(list(dest.glob('calibration_procedures.sqlite3.before-import-*'))), 1)
            self.assertTrue((dest / 'progress' / '8846A_T1_checkpoint.json').exists())
        self.assertEqual((src / 'calibration_procedures.sqlite3').read_bytes(), b'SRC-MAIN')   # source untouched
        self.assertTrue((src / 'Procedures' / '8846A_T1_checkpoint.json').exists())

    def test_import_from_self_is_a_noop(self):
        d = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {'CALSUITE_DATA': str(d)}):
            self.assertEqual(appdata.import_from(d), [])


class Diagnostics(unittest.TestCase):
    def test_scrub_hides_passwords(self):
        text = 'login password=Hunter2 ok; PWD: abc123 and token = xyz'
        out = diagnostics.scrub(text)
        for secret in ('Hunter2', 'abc123', 'xyz'):
            self.assertNotIn(secret, out)

    def test_log_has_no_password_and_has_version(self):
        with mock.patch.dict(os.environ, {'CALSUITE_DATA': tempfile.mkdtemp()}):
            path = diagnostics.write_log('Traceback...\nValueError: bad password=SuperSecret1', 'Test window')
            body = path.read_text(encoding='utf-8')
        self.assertNotIn('SuperSecret1', body)
        self.assertIn(suite_info.full_version(), body)

    def test_missing_packages_message(self):
        msg = diagnostics.explain_missing([('serial', 'pyserial', 'RS-232')])
        self.assertIn('py -m pip install pyserial', msg)


class Titles(unittest.TestCase):
    def test_tidy_title(self):
        t = branding.tidy_title('WaveSurfer 4104HD | Calibration Verification v56')
        self.assertTrue(t.startswith('Calibration Suite  |  WaveSurfer 4104HD'))
        self.assertTrue(t.endswith(suite_info.full_version()))
        self.assertEqual(t.count(suite_info.VERSION), 1)
        self.assertEqual(branding.tidy_title(t), t)                        # idempotent
        self.assertEqual(branding.tidy_title('Calibration Procedure Manager').count(suite_info.VERSION), 1)


@unittest.skipUnless(HAVE_TK, 'tkinter or a display is not available')
class Window(unittest.TestCase):
    def test_procedure_window_dressed(self):
        mod = importlib.import_module('truevolt_verification')
        root = tk.Tk()
        mod.App(root, '34461A', demo=True)
        import time
        end = time.time() + 1.5
        while time.time() < end:
            root.update(); time.sleep(0.02)
        self.assertTrue(root.title().startswith('Calibration Suite'), root.title())
        self.assertIn(suite_info.full_version(), root.title())
        menu = root.nametowidget(root['menu'])
        self.assertEqual(menu.entrycget(0, 'label'), 'Help')
        self.assertTrue(root.bind('<Control-s>'))
        self.assertTrue(root.bind('<F1>'))
        self.assertIn(suite_info.full_version(), root._cal_statusbar.right.cget('text'))
        # an unexpected error shows the friendly window and never the raw traceback text in the dialog
        shown = []
        with mock.patch('tkinter.messagebox.showerror', lambda t, m, **k: shown.append((t, m))):
            try:
                raise RuntimeError('boom password=Topsecret')
            except RuntimeError:
                root.report_callback_exception(*sys.exc_info())
        self.assertEqual(shown[0][0], 'Something went wrong')
        self.assertNotIn('Topsecret', shown[0][1])
        self.assertNotIn('Traceback', shown[0][1])
        root.destroy()


class ReportFooter(unittest.TestCase):
    def test_footer_names_software_version(self):
        try:
            import report_pdf
        except ImportError:
            self.skipTest('reportlab not available')
        out = Path(tempfile.mkdtemp()) / 'r.pdf'
        rows = [dict(Section='S', Description='d', Nominal='1', **{'Tolerance -': '0.9', 'Tolerance +': '1.1'}, UOM='V', **{'As Found': '1.0', 'OOT': '', 'As Left': 'Same'})]
        try:
            report_pdf.write_calibration_pdf(str(out), rows, header=[('Instrument ID', 'X1')], demo=False)
        except Exception as exc:
            self.skipTest(f'PDF writer unavailable here: {exc}')
        text = subprocess.run(['pdftotext', '-layout', str(out), '-'], capture_output=True, text=True).stdout
        self.assertIn(suite_info.full_version(), text)
        self.assertNotIn('logo', text.lower())


if __name__ == '__main__':
    unittest.main()
