"""WP-S: the shared helpers (run queue, manual override, data mode, procmods mixin, reset, surprise, the theme split) are toolkit-free.

  * Static: the toolkit-free helper files import no tkinter / ui_shell / report_dialog, use only the pure ui_theme helpers, and call nothing on `<x>.root`
    (tests/ui_ported.txt line `shared`; the `*_view_tk.py` files of that line are the Tk window code and may use tkinter).
  * Run time: in the `shared` prompt scenario (tests/ui_prompt_capture._run_shared) every prompt that belongs to a shared helper arrives through the port
    (origin 'port'); the handheld engine's own prompts still go through its Tk calls until its port lands.
  * ui_theme_core imports no toolkit, and ui_theme re-exports it (same objects), SCALE / THEME / DEMO_SUFFIX read through.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import ui_ported  # noqa: E402
from tests import ui_prompt_capture as C  # noqa: E402
from tests.test_ui_port_clean import problems  # noqa: E402

# titles shown by the shared helpers (run_queue_engine, manual_override, datamode, procmods_engine, reset_startup)
SHARED_TITLES = {'Next meter', 'One meter at a time', 'Resume saved progress', 'Reports', 'No results', 'Run queue', 'Queue reports',
                 'Enter reading manually', 'Instrument ID', 'Replace the As Found reading?', 'Section', 'Reset failed - run not started', 'Reset instruments'}


def shared_files():
    return [f for f in ui_ported.entries()['shared'] if f.endswith('.py') and not f.endswith('_view_tk.py') and f != 'ui_theme.py']


class SharedHelpersAreToolkitFree(unittest.TestCase):
    def test_static(self):
        for f in shared_files():
            self.assertEqual([p for p in problems(ROOT / f) if p != 'does not import ui_port'], [], f)

    def test_the_view_files_exist_next_to_their_helpers(self):
        for f in ui_ported.entries()['shared']:
            self.assertTrue((ROOT / f).exists(), f)


class PromptsArriveThroughThePort(unittest.TestCase):
    def test_shared_titles_use_the_port(self):
        got = C.capture('shared', C.PortHarness)
        seen = 0
        for name, records in got.items():
            origins = C.ORIGINS[name]
            self.assertEqual(len(origins), len(records), name)
            for rec, origin in zip(records, origins):
                queue_annunciator = rec['title'] == 'AC annunciator' and 'Meter: asset' in rec['text']          # the single-meter one is handheld_dmm's own
                if rec['kind'] != 'ask_reading' and (rec['title'] in SHARED_TITLES or rec['title'].startswith('Note for point') or queue_annunciator):
                    seen += 1
                    self.assertEqual(origin, 'port', f'{name}: {rec["title"]} bypassed the port')
        self.assertGreater(seen, 20)


class ThemeSplit(unittest.TestCase):
    def test_core_imports_no_toolkit(self):
        tree = ast.parse((ROOT / 'ui_theme_core.py').read_text(encoding='utf-8'))
        mods = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {(n.module or '').split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(mods & {'tkinter', 'PySide6', 'PyQt5', 'PyQt6'}, mods)

    def test_ui_theme_reexports_the_same_objects(self):
        import _tk_stub
        _tk_stub.install()
        import ui_theme
        import ui_theme_core as core
        for name in ('LIGHT', 'DARK', 'PALETTES', 'C', 'KINDS', 'theme_choice', 'use_palette', 'is_dark', 'px', 'si_scale', 'si_one', 'si_row', 'si', 'fmt_num',
                     'status_kind', 'Settings', 'report_filename'):
            self.assertIs(getattr(ui_theme, name), getattr(core, name), name)

    def test_rebound_values_read_through(self):
        import _tk_stub
        _tk_stub.install()
        import ui_theme
        import ui_theme_core as core
        old = core.DEMO_SUFFIX, core.THEME, core.SCALE
        try:
            core.DEMO_SUFFIX, core.SCALE = ' [DEMO]', 1.5
            core.use_palette('dark')
            self.assertEqual((ui_theme.DEMO_SUFFIX, ui_theme.THEME, ui_theme.SCALE, ui_theme.is_dark()), (' [DEMO]', 'dark', 1.5, True))
            self.assertEqual(ui_theme.px(10), 15)
        finally:
            core.DEMO_SUFFIX, core.SCALE = old[0], old[2]
            core.use_palette(old[1])
        with self.assertRaises(AttributeError):
            ui_theme.NO_SUCH_NAME


if __name__ == '__main__':
    unittest.main()
