"""The right-click menu of a Procedures row (procedure_menu.py), the Run buttons at the top of the tab and the removed Procedure Development tab.
Model level and source level only; the real windows are driven by tests/real_tk_checks.py (checks_manager_run_top / checks_manager_row_menu)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import procedure_menu as PM  # noqa: E402


def entries(**kw):
    args = dict(found=True, verify=('Mark verified on hardware...', True), lock=('Unlock for editing...', False), can_show=True, has_path=True, restorable=False)
    args.update(kw)
    return PM.items(**args)


def by_key(items):
    return {i.key: i for i in items if i}


class MenuItems(unittest.TestCase):
    def test_labels_and_order(self):
        self.assertEqual(PM.labels(entries()), ['Run procedure', 'Try in demo mode (virtual instruments)', 'Readiness check (no hardware)...', '-', 'Mark verified on hardware...', 'Unlock for editing...', '-',
                                                'Restore previous version...', 'Remove from library', '-', 'Copy procedure name', 'Copy file path', 'Show file location'])

    def test_run_and_demo_follow_the_ready_pill(self):
        for found in (True, False):
            m = by_key(entries(found=found))
            self.assertEqual((m['run'].enabled, m['demo'].enabled), (found, found))

    def test_verify_and_lock_take_the_buttons_text_and_state(self):
        m = by_key(entries(verify=('Mark verified again...', False), lock=('Lock again', True)))
        self.assertEqual((m['verify'].label, m['verify'].enabled, m['lock'].label, m['lock'].enabled), ('Mark verified again...', False, 'Lock again', True))

    def test_restore_needs_a_backup(self):
        self.assertFalse(by_key(entries())['restore'].enabled)
        self.assertTrue(by_key(entries(restorable=True))['restore'].enabled)

    def test_remove_is_always_offered_and_copy_show_follow_the_file(self):
        m = by_key(entries(found=False, can_show=False, has_path=False))
        self.assertTrue(m['remove'].enabled)
        self.assertEqual((m['copy_name'].enabled, m['copy_path'].enabled, m['show'].enabled), (True, False, False))


class ManagerSource(unittest.TestCase):
    src = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')

    def test_development_tab_is_gone_and_its_features_moved(self):
        for gone in ('development_frame', 'build_development_tab', 'refresh_development', 'Procedure Development', 'def install_update', 'Install update', 'def test_demo', 'dev_info', 'backup_table'):
            self.assertNotIn(gone, self.src)
        tabs = re.findall(r"self\.notebook\.add\(self\.\w+, text='\s*([^']+?)\s*'\)", self.src)
        self.assertEqual(tabs, ['Procedures', 'Asset History', 'Standards Specs', 'Datasheet Builder'])
        self.assertIn("text='Library folder...'", self.src)
        self.assertIn('def restore_previous', self.src)
        self.assertIn('procedure_menu.RESTORE: self.restore_previous', self.src)

    def test_run_buttons_are_in_the_pinned_part_of_the_card(self):
        card = self.src.index("card = ttk.LabelFrame(split, text='Selected procedure'")
        self.assertIn("self.btn_run = ttk.Button(run_row, text='\\u25b6 Run'", self.src)
        self.assertIn("self.btn_demo = ttk.Button(run_row, text='Try in demo mode'", self.src)
        self.assertGreater(self.src.index('self.btn_run = ttk.Button(run_row'), card)
        self.assertNotIn('runbar', self.src)                                       # the big row under the view strip is gone
        # pinned: packed to the bottom of the card BEFORE the scrolling part, so a short window never squeezes it out
        self.assertLess(self.src.index("pinned.pack(side='bottom'"), self.src.index('self.card_scroll = ui.ScrollFrame(card'))
        self.assertIn("Select a procedure, then press Run procedure (or Try in demo mode).", self.src)

    def test_short_verify_texts_keep_the_full_text(self):
        for full, short in (('Mark verified on hardware...', 'Mark verified...'), ('Mark verified again...', 'Verify again...'),
                            ('Unlock for editing...', 'Unlock...'), ('Lock again (nothing changed)', 'Lock again')):
            self.assertIn(f"'{full}': '{short}'", self.src)
        self.assertIn('b.full_text', self.src)

    def test_every_tab_page_can_scroll(self):
        self.assertEqual(self.src.count('= self._scroll_page()'), 3)
        self.assertIn('ui.ScrollFrame(card', self.src)


if __name__ == '__main__':
    unittest.main()
