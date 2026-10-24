"""An engine listed in tests/ui_ported.txt must be toolkit-free: no tkinter in it, every dialog / scheduler / window call through ui_port.

Static (the engine is parsed, never run).  What is checked in the engine file (the first file of its ui_ported line):
  * no import of tkinter (or a submodule), ui_shell, report_dialog; no use of the names tk / ttk / messagebox / filedialog / simpledialog;
  * `import ui_theme as ui` only for its toolkit-free helpers (PURE_THEME below): no ui.confirm_steps, ui.dialog, ui.apply_theme, ...;
  * nothing is called on a window object (`<x>.root.<anything>`: after, destroy, title, update_idletasks, ...): that is port.post / after / close / flush / set_title;
  * ui_port is imported.
The window code lives in the engine's `<VIEW>_tk.py`, which may use tkinter freely.  Transitive imports (the shared mixins datamode / virtualbench / procmods_engine /
ui_theme still import tkinter) are NOT checked: they are the shared-helpers work package (NOTES.md 'UiPort').
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import ui_ported  # noqa: E402

PURE_THEME = {'si_row', 'si_one', 'si', 'report_filename', 'Settings', 'fmt_num', 'status_kind'}
BANNED_NAMES = {'tk', 'ttk', 'messagebox', 'filedialog', 'simpledialog', 'tkinter'}
BANNED_MODULES = {'tkinter', 'ui_shell', 'report_dialog'}


def problems(path):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    out, imports_port, theme_names = [], False, {'ui_theme'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split('.')[0] in BANNED_MODULES:
                    out.append(f'line {node.lineno}: import {a.name}')
                if a.name == 'ui_port':
                    imports_port = True
                if a.name == 'ui_theme' and a.asname:
                    theme_names.add(a.asname)
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or '').split('.')[0]
            if mod in BANNED_MODULES:
                out.append(f'line {node.lineno}: from {node.module} import ...')
            if mod == 'ui_port':
                imports_port = True
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            out.append(f'line {node.lineno}: name {node.id}')
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in theme_names and node.attr not in PURE_THEME:
                out.append(f'line {node.lineno}: {node.value.id}.{node.attr} (not a toolkit-free ui_theme helper)')
            if isinstance(node.value, ast.Attribute) and node.value.attr == 'root':
                out.append(f'line {node.lineno}: .root.{node.attr} (window call outside the port)')
    if not imports_port:
        out.append('does not import ui_port')
    return out


class PortedEnginesAreToolkitFree(unittest.TestCase):
    def test_each_ported_engine(self):
        for key, engine in ui_ported.engine_files().items():
            self.assertEqual(problems(ROOT / engine), [], f'{key}: {engine}')

    def test_the_check_catches_a_leftover(self):
        import tempfile
        bad = Path(tempfile.mkdtemp()) / 'bad.py'
        bad.write_text('import tkinter as tk\nimport ui_theme as ui\nfrom tkinter import messagebox\nclass A:\n    def f(self):\n        ui.confirm_steps(self.root, 1)\n        self.root.after(0, f)\n', encoding='utf-8')
        found = problems(bad)
        self.assertTrue(any('import tkinter' in x for x in found) and any('confirm_steps' in x for x in found) and any('.root.after' in x for x in found), found)


if __name__ == '__main__':
    unittest.main()
