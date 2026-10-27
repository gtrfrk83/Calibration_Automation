"""2-wire impedance compensation (ZCOMP WIRE2) on handheld-meter resistance points, owner request 2026-10-27 (Fluke 289 with the 5560A did not enable it).
5560A Remote Programmers Manual p. 122 (ZCOMP / ZCOMP?), 5522A Operators Manual p. 6-49 (allowed below 110 kohm).  The 5520A manual does not show ZCOMP: not sent.
The engine run uses the 325 (nine resistance points, all below 110 kohm); the 287/289 high-resistance points are checked against a stub calibrator.
tkinter is stubbed in setUpModule.   Run:  python -m unittest tests.test_handheld_zcomp"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tests import test_fluke_323_points as T   # noqa: E402


def setUpModule():
    T.setUpModule()


def tearDownModule():
    T.tearDownModule()


class ZcompOnResistance(unittest.TestCase):
    setUp = T.EndToEnd.setUp
    tearDown = T.EndToEnd.tearDown
    make = T.EndToEnd.make
    run_perfect = T.EndToEnd.run_perfect

    def wire(self, cal):
        app, io = self.run_perfect('325', cal)
        self.n_ohm = sum(1 for p in T.pts('325') if p['kind'] == 'OHM')
        return [t for _i, t in T.H.wire(io)]

    def test_wire2_after_each_resistance_output_with_either_calibrator(self):
        for cal in ('5560A', '5522A'):
            texts = self.wire(cal)
            ons = [i for i, t in enumerate(texts) if t == 'ZCOMP WIRE2']
            self.assertEqual(len(ons), self.n_ohm, cal)
            for i in ons:
                self.assertRegex(texts[i - 1], r'^OUT [-0-9.e+]+OHM$')
                self.assertEqual(texts[i + 1], 'ZCOMP?')                       # read back, never re-sent
                self.assertIn('OPER', texts[i + 2:i + 8])
            self.assertEqual(sum(1 for t in texts if t == 'ZCOMP NONE'), self.n_ohm, cal)
            self.assertEqual(texts[-1], 'STBY')
            self.assertEqual(sum(1 for t in texts if t == 'ZCOMP WIRE2'), len(ons))   # exactly once per point
            self.hn.stop(); self.hn = T.H.Harness().start()

    def test_no_zcomp_for_other_functions(self):
        texts = self.wire('5560A')
        for i, t in enumerate(texts):
            if t == 'ZCOMP WIRE2':
                self.assertTrue(texts[i - 1].endswith('OHM'))


class Limits(unittest.TestCase):
    def test_allowed_below_110k_only_and_not_on_5520a(self):
        from drivers.fluke_5560a import Fluke5520A, Fluke5522A, Fluke5560A
        for cls in (Fluke5560A, Fluke5522A):
            self.assertTrue(cls.zcomp_allowed(cls, 50e3)); self.assertTrue(cls.zcomp_allowed(cls, 0))
            self.assertFalse(cls.zcomp_allowed(cls, 110e3)); self.assertFalse(cls.zcomp_allowed(cls, 300e6))
        self.assertFalse(Fluke5520A.zcomp_allowed(Fluke5520A, 100))

    def test_commands_verified_and_in_registry(self):
        from drivers.fluke_5560a import Fluke5560A
        for k in ('zcomp.set', 'zcomp.query'):
            self.assertTrue(Fluke5560A.COMMANDS[k].verified)
            self.assertIn('p. 122', Fluke5560A.COMMANDS[k].ref)

    def test_set_zcomp_raises_on_readback_mismatch_and_does_not_retry(self):
        from drivers.base import InstrumentError
        from drivers.fluke_5560a import Fluke5560A
        sent = []
        class Stub(Fluke5560A):
            def __init__(self): self.label = 'stub'
            def send(self, name, **kw): sent.append((name, kw))
            def ask(self, name, **kw): return 'NONE'
        with self.assertRaises(InstrumentError):
            Stub().set_zcomp('WIRE2')
        self.assertEqual(len(sent), 1)


if __name__ == '__main__':
    unittest.main()


class ResetAfterHandSet(unittest.TestCase):
    """Fluke 287/289 (owner request 2026-10-27): the calibrator is reset after a point the operator set by hand (steps 25, 29 duty cycle, 41), before the next point's commands."""

    def run_io(self, option, pending=True):
        import handheld_dmm as hd
        from drivers.simulated import make_bench
        spec = hd.load_spec('fluke_287_289_pv.json')
        self.assertTrue(spec['options'].get('reset_after_hand_set'))
        hand = [p for p in hd.points_for(spec, '289') if p['kind'] == 'NONE' and 'by hand' in p.get('setup', '')]
        self.assertEqual(len(hand), 3)
        nxt = next(p for p in hd.points_for(spec, '289') if p['kind'] == 'DCV')
        bench, _a, _b = make_bench()
        io = hd.IO('Fluke 5522A', 'sim', transport=T.Spy(bench, '5522A'))
        io.auto_ramp = False
        io.reset_after_hand_set = option
        io.hand_set_pending = pending
        io.apply(nxt)
        return io, [t for _i, t in T.H.wire(io)]

    def test_reset_before_the_next_points_first_output_command(self):
        io, texts = self.run_io(True)
        self.assertEqual(texts.count('*RST'), 1)
        first_out = next(i for i, t in enumerate(texts) if t.startswith('OUT ') and not t.endswith('?'))
        self.assertLess(texts.index('*RST'), first_out)
        self.assertFalse(io.hand_set_pending)

    def test_no_reset_when_nothing_was_set_by_hand_or_option_off(self):
        self.assertNotIn('*RST', self.run_io(True, pending=False)[1])
        self.assertNotIn('*RST', self.run_io(False)[1])
