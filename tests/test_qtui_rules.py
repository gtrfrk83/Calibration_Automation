"""The qtui/ package rules (static; needs no PySide6, so it also runs on the Tk-only machines):
  * no Tk anywhere in qtui/ (tkinter, ui_theme, ui_shell, ui_port_tk, *_view_tk);
  * theme.py / widgets.py / table.py import only PySide6, the standard library, ui_theme_core and qtui itself (no instrument, driver or engine code);
  * every qtui module reaches the engines only through ui_port (app.py may import nothing but PySide6 / stdlib / qtui as well, today)."""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QTUI = ROOT / 'qtui'
TK_NAMES = {'tkinter', 'ttk', 'ui_theme', 'ui_shell', 'ui_port_tk'}
PURE = ('theme.py', 'widgets.py', 'table.py')


def imports(path):
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append(('.' * node.level) + (node.module or ''))
    return out


class QtuiRules(unittest.TestCase):
    def files(self):
        return sorted(QTUI.glob('*.py'))

    def test_package_exists(self):
        self.assertTrue((QTUI / '__init__.py').exists())

    def test_no_tk_in_qtui(self):
        for f in self.files():
            for name in imports(f):
                top = name.lstrip('.').split('.')[0]
                self.assertNotIn(top, TK_NAMES, f'{f.name} imports {name}')
                self.assertFalse(top.endswith('_view_tk'), f'{f.name} imports {name}')

    def test_design_modules_import_no_engine_or_instrument_code(self):
        stdlib = set(sys.stdlib_module_names)
        for fname in PURE:
            for name in imports(QTUI / fname):
                top = name.lstrip('.').split('.')[0]
                ok = name.startswith('.') or top in stdlib or top in ('PySide6', 'ui_theme_core', 'qtui', '__future__')
                self.assertTrue(ok, f'qtui/{fname} imports {name}: only PySide6, the standard library, ui_theme_core and qtui are allowed')

    def test_app_imports_nothing_but_qt_stdlib_and_qtui(self):
        stdlib = set(sys.stdlib_module_names)
        for name in imports(QTUI / 'app.py'):
            top = name.lstrip('.').split('.')[0]
            self.assertTrue(name.startswith('.') or top in stdlib or top in ('PySide6', 'ui_theme_core', 'qtui'), name)


if __name__ == '__main__':
    unittest.main()
