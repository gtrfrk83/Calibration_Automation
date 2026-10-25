"""qtui.theme: token coverage against ui_theme_core, QSS generation, contrast of the dark palette, theme choice / saved setting, live switching.
Skipped when PySide6 is not importable (Tk-only dev machines).  Headless: QT_QPA_PLATFORM=offscreen."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    import ui_theme_core as core
    from qtui import app, theme


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def tearDown(self):
        theme.set_theme('dark')

    def test_every_core_key_has_a_decision(self):
        for name, pal in core.PALETTES.items():
            keys = set(pal)
            covered = set(theme.REQUIRED_KEYS) | set(theme.TK_ONLY)
            self.assertEqual(keys - covered, set(), f'{name}: ui_theme_core keys with no Qt counterpart or TK_ONLY entry')
            self.assertEqual(set(theme.REQUIRED_KEYS) - keys, set(), f'{name}: REQUIRED_KEYS missing from the palette')

    def test_tokens_are_hex_colours_and_pairs_are_split(self):
        for name in core.PALETTES:
            t = theme.build_tokens(name)
            for k in theme.REQUIRED_KEYS:
                if k in ('btn', 'btn_hi', 'btn_lo', 'btn_off'):
                    self.assertRegex(t[k], r'^#[0-9A-Fa-f]{6}$')
                    self.assertRegex(t[k + '_border'], r'^#[0-9A-Fa-f]{6}$')
                else:
                    self.assertRegex(t[k], r'^#[0-9A-Fa-f]{6}$', f'{name}.{k}')
            for k in ('disabled_fg', 'focus', 'primary_off_fg', 'placeholder', 'tooltip_fg'):
                self.assertRegex(t[k], r'^#[0-9A-Fa-f]{6}$', k)

    def test_qss_is_fully_resolved(self):
        for name in core.PALETTES:
            q = theme.build_qss(theme.build_tokens(name))
            self.assertNotIn("{t[", q)
            self.assertNotIn('None', q)
            for sel in ('QPushButton[role="primary"]', 'QLabel[badge="bad"]', 'QTableView', 'QHeaderView::section', 'QProgressBar::chunk', ':focus'):
                self.assertIn(sel, q)
            self.assertEqual(q.count('{'), q.count('}'))

    def test_dark_palette_is_legible(self):
        t = theme.build_tokens('dark')
        self.assertGreaterEqual(theme.contrast(t['text'], t['bg']), 7)
        self.assertGreaterEqual(theme.contrast(t['muted'], t['bg']), 4.5)
        self.assertGreaterEqual(theme.contrast(t['muted'], t['table']), 4.5)
        self.assertGreaterEqual(theme.contrast(t['on_primary'], t['primary']), 2.4)          # white on the lighter dark-theme blue (bold label)
        for kind in theme.KINDS:
            self.assertGreaterEqual(theme.contrast(t[kind], t[kind + '_bg']), 4.5, f'badge {kind}')
        # disabled controls must stay readable (not WCAG-exempt in this app: the operator has to see what is unavailable)
        self.assertGreaterEqual(theme.contrast(t['disabled_fg'], t['disabled_bg']), 3.0)
        self.assertGreaterEqual(theme.contrast(t['disabled_fg'], t['field']), 3.0)
        self.assertGreaterEqual(theme.contrast(t['primary_off_fg'], t['primary_off']), 3.0)
        self.assertGreaterEqual(theme.contrast(t['focus'], t['bg']), 3.0)                    # the focus ring against the window

    def test_start_up_choice(self):
        self.assertEqual(theme.ENABLED_THEMES, ('dark', 'light'))
        for env, want in (('light', 'light'), ('dark', 'dark'), ('nonsense', 'dark'), ('', 'dark')):
            with mock.patch.dict(os.environ, {'CALSUITE_THEME': env}):
                self.assertEqual(theme.manager().apply_initial(), want)
        theme.manager().set_theme('dark')

    def test_saved_choice_uses_the_same_store_as_tk(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}):
            theme.set_theme('dark', save=True)
            f = Path(home) / '.calibration_suite' / 'appearance.json'
            self.assertTrue(f.exists())
            self.assertEqual(core.Settings('appearance').get('theme'), 'dark')

    def test_live_switch_restyles_and_notifies(self):
        seen = []
        theme.manager().changed.connect(seen.append)
        before = self.app.styleSheet()
        theme.set_theme('light')                       # plumbing only: light is not offered or polished
        self.assertEqual(seen[-1], 'light')
        self.assertEqual(core.THEME, 'light')
        self.assertEqual(theme.tokens()['name'], 'light')
        self.assertNotEqual(self.app.styleSheet(), before)
        theme.set_theme('dark')
        self.assertEqual(seen[-2:], ['light', 'dark'])
        self.assertEqual(self.app.styleSheet(), before)
        theme.manager().changed.disconnect(seen.append)

    def test_fonts_resolve(self):
        self.assertTrue(theme.font_family())
        self.assertTrue(theme.mono_family())
        f = theme.ui_font()
        self.assertEqual(f.pixelSize(), theme.M.font_base)

    def test_icons_render(self):
        for n in theme.ICON_NAMES:
            pm = theme.pixmap(n, '#ffffff', 16)
            self.assertFalse(pm.isNull(), n)
            img = pm.toImage()
            self.assertTrue(any(img.pixelColor(x, y).alpha() for x in range(img.width()) for y in range(img.height())), f'{n} drew nothing')


if __name__ == '__main__':
    unittest.main()
