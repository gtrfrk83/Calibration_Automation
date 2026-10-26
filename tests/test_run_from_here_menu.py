"""Right-click 'Run from here' on every point list that has a Rerun From (procmods_point_model.run_from_entry + the three menus)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import procmods_point_model as PM  # noqa: E402


class App:
    def __init__(self, **kw):
        self.calls = []
        self.__dict__.update(kw)

    def rerun_from(self):
        self.calls.append('from')


class Btn:
    def __init__(self, on):
        self.on = on

    def isEnabled(self):
        return self.on


class Entry(unittest.TestCase):
    def test_runs_the_same_action_as_the_button(self):
        a = App()
        label, cmd, ok, why = PM.run_from_entry(a)
        self.assertEqual((label, ok, why), ('Run from here', True, ''))
        cmd()
        self.assertEqual(a.calls, ['from'])

    def test_wavesurfer_name_is_used(self):
        class W:
            def rerun_from_selected(self):
                pass
        self.assertEqual(PM.run_from_entry(W())[0], 'Run from here')

    def test_none_without_rerun_from(self):
        self.assertIsNone(PM.run_from_entry(object()))

    def test_disabled_while_running(self):
        for kw in ({'busy': True}, {'_batch_busy': lambda: True}):
            r = PM.run_from_entry(App(**kw))
            self.assertFalse(r[2])
            self.assertTrue(r[3])

    def test_follows_the_button_state(self):
        self.assertFalse(PM.run_from_entry(App(btn_rerun_from=Btn(False)))[2])
        self.assertTrue(PM.run_from_entry(App(btn_rerun_from=Btn(True)))[2])

    def test_independent_of_the_edit_lock(self):
        a = App(pm_state=None)
        self.assertFalse(PM.menu_state(a, 'x')[0])
        self.assertTrue(PM.run_from_entry(a)[2])


class QtMenu(unittest.TestCase):
    def test_entries_hold_run_from_here(self):
        import procmods_view_qt as V
        a = App(pm_state=None)
        tm = V.TreeMenu(a, None, None)
        labels = [e[0] for e in tm.entries('p1')]
        self.assertIn('Run from here', labels)
        self.assertEqual(labels[0], 'Edit')
        a2 = object.__new__(App)
        a2.pm_state = None
        a2.calls = []
        a2.rerun_from = None
        self.assertNotIn('Run from here', [e[0] for e in V.TreeMenu(a2, None, None).entries('p1')])


if __name__ == '__main__':
    unittest.main()
