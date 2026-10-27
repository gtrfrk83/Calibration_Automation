"""The suite is Qt only (the Tk build was removed 2026-10-27).  Guards: no program file imports tkinter or one of the removed Tk modules, and the removed files stay removed.

Static (AST) so it needs neither PySide6 nor a display.  tests/ is excluded: tests/_tk_stub.py is a test-only stand-in that keeps the engine tests running
headless until each is moved to ui_port.ScriptedUiPort; it ships no toolkit and nothing in the program imports it.
"""
import ast
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMOVED = {'tkinter', 'ttk', 'ui_theme', 'ui_shell', 'ui_port_tk', 'branding', 'report_dialog', 'report_review', 'run_queue_ui', 'manual_grid',
           'datasheet_builder_ui', 'datasheet_builder_check_ui', 'specmanager_ui', 'spec_editor_ui', 'labregistry_ui', 'instrument_scan_ui',
           'mdd_import_ui', 'packages_ui', 'verified_ui', 'procmods_ui', 'procmods_point_ui', 'Calibration_Procedure_Manager'}


# The no-hardware readiness harness drives each launcher over tests/_tk_stub.py (stand-in modules, no toolkit); it is a test tool that happens to live in tools/.
HARNESS = {'tools/readiness_check.py', 'tools/readiness_run.py'}


def program_files():
    out = subprocess.run(['git', 'ls-files', '*.py'], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return [ROOT / f for f in out if not f.startswith('tests/') and f not in HARNESS and (ROOT / f).is_file()]


class NoTk(unittest.TestCase):
    def test_no_program_file_imports_tkinter_or_a_removed_tk_module(self):
        bad = []
        for path in program_files():
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    names = [node.module] + ([a.name for a in node.names] if node.module in ('.', '') else [])
                for n in names:
                    if n.split('.')[0] in REMOVED or n.endswith('_view_tk'):
                        bad.append(f'{path.relative_to(ROOT)}:{node.lineno} imports {n}')
        self.assertEqual(bad, [])

    def test_the_tk_files_are_gone(self):
        left = [p.name for p in ROOT.glob('*_view_tk.py')] + [n + '.py' for n in sorted(REMOVED) if n not in ('tkinter', 'ttk') and (ROOT / (n + '.py')).exists()]
        self.assertEqual(left, [])

    def test_the_default_toolkit_is_qt_and_there_is_no_other(self):
        import ui_port
        self.assertEqual(ui_port.TOOLKITS, ('qt',))
        self.assertEqual(ui_port.DEFAULT_TOOLKIT, 'qt')
        with self.assertRaises(ValueError):
            ui_port.select_toolkit('tk')

    def test_sidecars_name_no_tk_file(self):
        text = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'Procedures').glob('*.procedure.json'))
        self.assertNotIn('_view_tk', text)
        self.assertNotIn('ui_port_tk', text)


if __name__ == '__main__':
    unittest.main()
