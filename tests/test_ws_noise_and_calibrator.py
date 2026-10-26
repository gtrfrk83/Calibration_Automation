"""WaveSurfer 4104HD: the RMS noise test keeps the scope in Auto trigger with P1 on the channel under test, and the calibrator box offers the 5560A, 5522A and 5520A.
(owner, 2026-10-26: P1 StdDev was frozen with the acquisition stopped and did not follow the channel; add 5520/5522 to the connections table.)
Simulated bench only; the Auto / P1 commands are the driver's existing registry entries (trig.mode.set is still marked unverified in the registry)."""
import queue
import sys
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'Procedures')]
W = None


def setUpModule():
    global W
    from tests import _tk_stub
    _tk_stub.install()                      # tkinter stubbed where it is missing
    import WaveSurfer_WS4104HD as mod
    W = mod


class Calibrator(unittest.TestCase):
    def test_choices_and_names(self):
        self.assertEqual(W.CAL_CHOICES, ['Fluke 5560A', 'Fluke 5522A', 'Fluke 5520A'])
        a = W.RMSNoiseApp.__new__(W.RMSNoiseApp)
        for choice, name in zip(W.CAL_CHOICES, ('5560A', '5522A', '5520A')):
            a._cal_choice = choice
            self.assertEqual((a.cal_name(), a.cal_std()), (name, name))

    def test_open_bench_picks_the_driver(self):
        import drivers
        a = W.RMSNoiseApp.__new__(W.RMSNoiseApp)
        seen = []
        orig = drivers.open_visa
        drivers.open_visa = lambda addr, **kw: seen.append(addr) or object()
        try:
            for choice, cls in (('Fluke 5560A', drivers.Fluke5560A), ('Fluke 5522A', drivers.Fluke5522AScope), ('Fluke 5520A', drivers.Fluke5522AScope)):
                a._cal_choice = choice
                f, s = a.open_bench('ASRL9::INSTR', 9600, None, drivers.CommandLog())
                self.assertIs(type(f), cls, choice)
                self.assertIsNone(s)
        finally:
            drivers.open_visa = orig


class Noise(unittest.TestCase):
    def test_worker_sets_auto_and_p1_channel_before_reading(self):
        import drivers
        from drivers.simulated import make_bench
        _b, _ft, st = make_bench()
        log = drivers.CommandLog()
        a = W.RMSNoiseApp.__new__(W.RMSNoiseApp)
        a.events, a.stop_event = queue.Queue(), threading.Event()
        a.open_bench = lambda fa, baud, sa, lg, scope_timeout=10: (None, drivers.WaveSurfer4104HD(st, log))
        a.reset_bench = lambda fluke, scope, lg: None
        a.save_command_log = lambda lg, name: None
        a.finish_bench = lambda fluke, scope, lg, name: scope.close()
        W.RMSNoiseApp.worker(a, 'sim', 3, 0.0, 1, 2.75, [10.0] * len(W.SCALES), 0, 2)
        sent = [t for _ts, _who, d, t in log.entries if d == '>>']
        self.assertIn('VBS \'app.Acquisition.TriggerMode="Auto" \'', sent)
        self.assertTrue(any('P1.Source1="C3"' in t for t in sent), sent)
        first_read = next(i for i, t in enumerate(sent) if 'P1.Out.Result.Value' in t)
        self.assertLess(sent.index('VBS \'app.Acquisition.TriggerMode="Auto" \''), first_read)       # Auto before the first value is read
        for ch in (1, 2, 3, 4):                                                    # all four channels ON, DC 1 MOhm, full bandwidth (the test's stated setup)
            self.assertTrue(any(f'C{ch}.View=True' in t for t in sent), ch)
            self.assertTrue(any(f'C{ch}.Coupling="DC1M"' in t for t in sent), ch)
            self.assertTrue(any(f'C{ch}.BandwidthLimit="Full"' in t for t in sent), ch)
        self.assertTrue(any('HorScale=0.001' in t for t in sent), sent)
        self.assertLess(max(i for i, t in enumerate(sent) if 'Acquisition.C' in t and '.View=True' in t), first_read)         # channels are set up before P1 is read
        kinds = [e[0] for e in list(a.events.queue)]
        self.assertNotIn('error', kinds, list(a.events.queue))
        self.assertEqual(kinds.count('row'), 2)


class NoData(unittest.TestCase):
    def test_p1_is_waited_for_not_failed_on_no_data_available(self):
        import drivers
        from drivers.base import InstrumentError
        sc = drivers.WaveSurfer4104HD.__new__(drivers.WaveSurfer4104HD)
        replies = ['No Data Available', 'No Data Available', '0.00042']
        calls = []

        def fake_get(key, path=None, **kw):
            calls.append(key)
            return replies.pop(0)
        sc._get = fake_get
        value = sc.read_p1_when_ready(timeout_s=5, interval_s=0.0)
        self.assertEqual((value, len(calls)), (0.00042, 3))
        sc._get = lambda *a, **k: 'No Data Available'
        with self.assertRaises(InstrumentError):                                         # still no data after the time: the scope's own message
            sc.read_p1_when_ready(timeout_s=0.05, interval_s=0.01)


if __name__ == '__main__':
    unittest.main()
