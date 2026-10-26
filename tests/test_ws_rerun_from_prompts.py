"""WaveSurfer 'Rerun From Selected': the connection prompt of a retest is asked for the first point and again only when the function or channel changes
(owner, 2026-10-26: a prompt on every point).  A single Rerun Selected always asks."""
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


class Chain(unittest.TestCase):
    def make(self):
        a = W.RMSNoiseApp.__new__(W.RMSNoiseApp)
        a.asked = []
        W.port.operator_prompt = lambda *args, **kw: a.asked.append(args[0]) or True
        return a

    def test_single_rerun_always_asks(self):
        a = self.make()
        for _ in range(3):
            self.assertTrue(a._retest_prompt('dcv', 4, 'Confirm DCV retest connection', 'x', []))
        self.assertEqual(len(a.asked), 3)

    def test_chain_asks_first_point_then_only_when_the_channel_or_function_changes(self):
        a = self.make()
        a._chain_last = None
        order = [('dcv', 4), ('dcv', 4), ('dcv', 4), ('dcv', 3), ('dcv', 3), ('offset', 3)]
        for i, (kind, ch) in enumerate(order):
            a._from_step_active = i > 0                                  # the first point is started by rerun_from_selected itself
            self.assertTrue(a._retest_prompt(kind, ch, f'prompt {kind} {ch}', 'x', []))
        self.assertEqual(a.asked, ['prompt dcv 4', 'prompt dcv 3', 'prompt offset 3'])

    def test_a_declined_prompt_ends_the_chain_point(self):
        a = self.make()
        W.port.operator_prompt = lambda *args, **kw: False
        a._chain_last = None
        self.assertFalse(a._retest_prompt('dcv', 4, 'p', 'x', []))
        self.assertIsNone(a._chain_last)


if __name__ == '__main__':
    unittest.main()
