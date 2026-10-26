"""The highlighted row follows the point being tested (owner, 2026-10-26): WaveSurfer (its section grids) and the scope engines TDS2000C / MDO3 / MDO4000C /
TBS2000B (the worker posts 'select' before every point; the pump selects and scrolls to the row)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'Procedures')]
W = None


def setUpModule():
    global W
    from tests import _tk_stub
    _tk_stub.install()
    import WaveSurfer_WS4104HD as mod
    W = mod


class FakeView:
    def __init__(self):
        self.selected = []

    def set_grid(self, tree, items, active=None):
        return [f'i{k}' for k in range(len(items))]

    def select_and_show(self, tree, iid):
        self.selected.append(iid)


class WaveSurferGrid(unittest.TestCase):
    def make(self, **flags):
        a = W.RMSNoiseApp.__new__(W.RMSNoiseApp)
        a.fake = FakeView()
        a.dc_tree = object()
        a.tree = object()
        for k, v in flags.items():
            setattr(a, k, v)
        W.port.view = lambda name: a.fake
        return a

    def test_follows_the_point_while_the_section_runs(self):
        a = self.make(dc_running=True, dc_retest_index=None)
        a._set_grid(a.dc_tree, [((), ())] * 5, active=2)
        self.assertEqual(a.fake.selected, ['i2'])

    def test_idle_refresh_leaves_the_selection_alone(self):
        a = self.make(dc_running=False, dc_retest_index=None)
        a._set_grid(a.dc_tree, [((), ())] * 5, active=2)
        self.assertEqual(a.fake.selected, [])

    def test_a_retest_keeps_the_retested_row(self):
        a = self.make(dc_running=True, dc_retest_index=1)
        a._set_grid(a.dc_tree, [((), ())] * 5, active=4)
        self.assertEqual(a.fake.selected, [])

    def test_nothing_after_the_last_point(self):
        a = self.make(dc_running=True, dc_retest_index=None)
        a._set_grid(a.dc_tree, [((), ())] * 5, active=5)
        self.assertEqual(a.fake.selected, [])

    def test_noise_grid_uses_the_running_flag(self):
        a = self.make(running=True, noise_retest_index=None)
        a._set_grid(a.tree, [((), ())] * 3, active=1)
        self.assertEqual(a.fake.selected, ['i1'])


class ScopeEngines(unittest.TestCase):
    def test_every_scope_worker_posts_select_and_pump_handles_it(self):
        for f in ('tds2000c_verification.py', 'mdo3_verification.py', 'mdo4000c_verification.py', 'tbs2000b_verification.py'):
            src = (ROOT / f).read_text(encoding='utf-8')
            self.assertIn("self.post('select', str(p['id']))", src, f)
            self.assertIn("elif kind == 'select':", src, f)
            self.assertLess(src.index("self.post('select'"), src.index('runner.run_point(p)'), f)


if __name__ == '__main__':
    unittest.main()
