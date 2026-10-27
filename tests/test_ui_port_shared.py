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


if __name__ == '__main__':
    unittest.main()
