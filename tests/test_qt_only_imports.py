"""The Qt-only build: every procedure, the user-datasheet runtime and the report modules import with tkinter unavailable (the engines use the
toolkit-free ui_theme_core helpers, not ui_theme).  Each import runs in a fresh interpreter with sys.modules['tkinter'] = None."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = '''
import sys, importlib, importlib.util
sys.path[:0] = [{root!r}, {procs!r}]
sys.modules['tkinter'] = None
for target in {targets!r}:
    if target.endswith('.py'):
        spec = importlib.util.spec_from_file_location('proc_under_test', target)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
    else:
        importlib.import_module(target)
print('OK')
'''


def run(targets):
    code = CHECK.format(root=str(ROOT), procs=str(ROOT / 'Procedures'), targets=list(targets))
    return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT), timeout=300)


class NoTkinter(unittest.TestCase):
    def test_every_procedure_imports_without_tkinter(self):
        for f in sorted((ROOT / 'Procedures').glob('*.py')):
            with self.subTest(procedure=f.name):
                r = run([str(f)])
                self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_runtime_and_report_modules_import_without_tkinter(self):
        r = run(['dsb_runtime', 'report_pdf', 'report_review_model', 'uncertainty', 'procspec', 'handheld_dmm', 'fgen_verification', 'truevolt_verification'])
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])

    def test_report_number_formatting_needs_no_tkinter(self):
        code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); sys.modules['tkinter'] = None\n"
                "import report_pdf, report_review_model, uncertainty\n"
                "print(report_pdf._si(0.0012, 'V'), report_pdf._freq_text(1e5), uncertainty.format_value(1.03e-3, 'V'))")
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertIn('kHz', r.stdout)


if __name__ == '__main__':
    unittest.main()
