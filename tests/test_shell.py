"""The redesigned window shell (sidebar, drawer, small-window layout, dark palette), in a real window with demo data."""
import os, sys, unittest
from tests.test_asleft import HAVE_TK, Harness, pump

if HAVE_TK:
    import ui_theme as ui


@unittest.skipUnless(HAVE_TK, 'tkinter or a display is not available')
class ShellOn8846A(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent / 'Procedures'))
        self.h = Harness('Fluke_8846A_Verification', lambda m, r: m.App(r, demo=True))
        self.addCleanup(self.h.close)
        self.app, self.root = self.h.app, self.h.root
        self.sh = self.app.shell

    def size(self, w, h):
        self.root.geometry(f'{w}x{h}'); self.root.update(); pump(self.root, lambda: False, 0.3)

    def test_beta_is_dark(self):
        self.assertTrue(ui.is_dark())
        self.assertEqual(ui.C['bg'], ui.DARK['bg'])

    def test_sidebar_follows_window_width(self):
        self.size(1440, 900)
        self.assertTrue(self.sh.sidebar.winfo_ismapped())
        self.size(900, 700)
        self.assertFalse(self.sh.sidebar.winfo_ismapped())
        self.assertTrue(self.sh.section_picker.winfo_ismapped())
        self.assertEqual(self.app.tree['displaycolumns'][3], 'limits')
        self.size(1440, 900)
        self.assertTrue(self.sh.sidebar.winfo_ismapped())

    def test_every_action_button_fits_at_900(self):
        self.size(900, 700)
        for b in self.sh.actions.winfo_children()[0:2]:
            for w in b.winfo_children():
                self.assertLessEqual(w.winfo_rootx() + w.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width() + 1, w.cget('text'))

    def test_drawer_opens_and_closes(self):
        self.sh.open_drawer(); self.root.update()
        self.assertTrue(self.sh.drawer.winfo_ismapped())
        self.assertTrue(self.app.dmm_combo.winfo_ismapped())
        self.sh.close_drawer(); self.root.update()
        self.assertFalse(self.sh.drawer.winfo_ismapped())

    def test_sidebar_section_filters_table(self):
        total = len(self.app.tree.get_children())
        name = self.sh.sections[0][0]
        self.sh.choose_section(name); self.root.update()
        shown = len(self.app.tree.get_children())
        self.assertTrue(0 < shown < total)
        self.sh.choose_section('All sections'); self.root.update()
        self.assertEqual(len(self.app.tree.get_children()), total)

    def test_as_left_columns(self):
        self.app.asset.set('T'); self.app.run_all()
        pump(self.root, lambda: not self.app.busy)
        first = self.app.tree.get_children()[0]
        self.assertEqual(self.app.tree.set(first, 'left'), '')
        self.app.set_data_mode('left'); self.root.update()
        self.assertEqual(self.app.tree.set(first, 'left'), 'Same')
        self.assertTrue(self.app.tree.set(first, 'found'))                       # As Found stays on screen, locked


if __name__ == '__main__':
    unittest.main()
