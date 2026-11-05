"""Fluke 8846A verification: the bench work ported from the old 8846a-settle-and-zero-block branch (owner bench sessions, Oct 2026) onto the Qt engine.

On the simulated bench (every reply here is simulated; the commands themselves are UNVERIFIED on a real 8846A):
  * settling: the tunable first wait stays as it was, the point-dependent extra comes on top, READ? is repeated until it is stable
  * FREQ / CAP / ACI points are automated (the AC filter is set and read back, the 5560A error queue is cleared first and read before OPER)
  * the 2-wire 100 ohm point: 0 ohm out, null the meter, then 100 ohm out and read; the null is always switched off again
  * a failed point saves its commands at once; the live command log never writes for a virtual (demo) session
  * points are looked up by id (the zero block is first, the list is not in id order); a loaded checkpoint is judged again against the current limits
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

import drivers  # noqa: E402
from drivers.simulated import make_dmm_bench  # noqa: E402
import Fluke_8846A_Verification as V  # noqa: E402


def make_io(**bench_attrs):
    bench, ft, dt = make_dmm_bench('8846A')
    for k, v in bench_attrs.items():
        setattr(bench, k, v)
    io = V.IO('1', '2', 9600, 'None', 8, transports=(dt, ft))          # transports given: the plain in-memory log, no live file
    return bench, io


def point(kind, **match):
    return next(p for p in V.POINTS if p['kind'] == kind and all(p.get(k) == v for k, v in match.items()))


class Waits(unittest.TestCase):
    def setUp(self):
        _b, self.io = make_io()

    def tearDown(self):
        self.io.close()

    def test_the_first_wait_is_the_tunable_and_the_point_dependent_extra_comes_on_top(self):
        zero = point('DCV', zero_offset=True)
        self.assertEqual(self.io.waits(zero), [1.5])                                  # 2.5 s - 1 s: nothing on top of the 1.5 s default
        acv = point('ACV')
        self.assertEqual(self.io.waits(acv), [3.5, 4.5])                              # 8 s in all: the 3 Hz filter settles slowly
        high_ohms = next(p for p in V.POINTS if p['kind'] == 'OHM2' and p['range'] >= 1e9 and not p.get('zero_offset'))
        self.assertEqual(self.io.waits(high_ohms), [2, 13.0])                         # 15 s in all: cable capacitance x GOhm

    def test_a_stored_first_wait_changes_only_the_first_sleep(self):
        acv = point('ACV')
        with mock.patch.object(self.io, 'pm_param', lambda name, default, point=None: 6.0 if name == 'f8846a.settle.ac' else default):
            self.assertEqual(self.io.waits(acv), [6.0, 4.5])

    def test_a_points_own_settle_time_replaces_both(self):
        p = dict(point('DCV'), settle_s=0.25)
        self.assertEqual(self.io.waits(p), [0.25])

    def test_an_unsettled_reading_is_read_again_and_a_note_is_logged_on_timeout(self):
        p = point('DCV')
        values = iter([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        clock = iter([0.0, 0.0, 1.0, 2.0, 3.0, 100000.0, 100001.0])
        with mock.patch.object(self.io, '_read', lambda: next(values)), mock.patch.object(V.time, 'sleep'), \
                mock.patch.object(V.time, 'monotonic', lambda: next(clock)):
            reading = self.io.settled_read(p)
        self.assertEqual(reading, 5.0)
        self.assertTrue(any('did not settle' in e[3] for e in self.io.log.entries))

    def test_three_agreeing_readings_end_the_wait(self):
        p = point('DCV')
        calls = []
        with mock.patch.object(self.io, '_read', lambda: calls.append(1) or 0.1), mock.patch.object(V.time, 'sleep'):
            self.assertEqual(self.io.settled_read(p), 0.1)
        self.assertEqual(len(calls), 3)


class Points(unittest.TestCase):
    def test_the_ac_frequency_and_capacitance_points_are_measured_with_their_commands(self):
        bench, io = make_io(freq_aware=True)
        try:
            with mock.patch.object(V.time, 'sleep'):
                acv = point('ACV')
                self.assertAlmostEqual(io.measure(acv), acv['nominal'], delta=acv['nominal'] * 1e-3)
                lines = io.log.lines()
                text = '\n'.join(lines)
                self.assertLess(text.index('CONF:VOLT:AC'), text.index('DET:BAND 3'))              # the filter is set after CONF (CONF resets it) ...
                self.assertLess(text.index('DET:BAND?'), text.index('OPER'))                       # ... and read back before the output is on
                io.log.entries.clear()
                frq = point('FREQ')
                self.assertAlmostEqual(io.measure(frq), frq['nominal'], delta=frq['nominal'] * 1e-3)
                text = '\n'.join(io.log.lines())
                self.assertIn('CONF:FREQ', text)
                self.assertIn('FREQ:APER 1', text)
                self.assertLess(text.index('*CLS'), text.index('OUT '))                              # the 5560A queue is cleared before this point
                self.assertLess(text.index('5560A       >>  ERR?') if '5560A       >>  ERR?' in text else text.index('ERR?'), text.index('OPER'))
                io.log.entries.clear()
                cap = point('CAP', zero_offset=False)
                self.assertGreater(io.measure(cap), 0)
        finally:
            io.close()

    def test_a_command_the_meter_rejects_names_itself_and_stops_the_point(self):
        bench, io = make_io(freq_aware=True)
        try:
            real = io.dmm.t.query

            def query(cmd, *a, **k):
                if cmd.strip().upper() == 'SYST:ERR?' and any('FREQ:APER' in e[3] for e in io.log.entries):
                    return '-113,"Undefined header"'
                return real(cmd, *a, **k)
            with mock.patch.object(io.dmm.t, 'query', query), mock.patch.object(V.time, 'sleep'), mock.patch.object(io, 'save_log') as saved:
                with self.assertRaises(drivers.InstrumentError) as cm:
                    io.measure(point('FREQ'))
            self.assertIn('FREQ:APER 1', str(cm.exception))
            self.assertTrue(saved.called)                                               # the failed point left its commands on disk at once
            self.assertNotIn('OPER', '\n'.join(io.log.lines()))                         # the output was never switched on
        finally:
            io.close()

    def test_the_2_wire_100_ohm_point_is_nulled_on_its_zero_reading(self):
        bench, io = make_io(lead_ohms=0.3)
        try:
            p = point('OHM2', range=100, nominal=100, zero_offset=False)
            self.assertTrue(V.needs_null(p))
            with mock.patch.object(V.time, 'sleep'):
                reading = io.measure(p)
            self.assertAlmostEqual(reading, 100.002, delta=0.01)                         # the 0.3 ohm of the leads is nulled out
            lines = [e[3] for e in io.log.entries if e[1] == '8846A' or True]
            text = '\n'.join(lines)
            self.assertLess(text.index('OUT 0OHM'), text.index('CALC:STAT ON'))
            self.assertLess(text.index('CALC:STAT ON'), text.index('OUT 100OHM'))
            self.assertTrue([l for l in lines if l.startswith(('CALC:STAT OFF', 'STBY'))][-1].startswith('CALC:STAT OFF'))      # the null is always switched off again
        finally:
            io.close()

    def test_the_null_is_switched_off_even_when_the_point_fails(self):
        bench, io = make_io(lead_ohms=0.3)
        try:
            p = point('OHM2', range=100, nominal=100, zero_offset=False)
            with mock.patch.object(V.time, 'sleep'), mock.patch.object(io.fluke, 'set_output_ohms', side_effect=[None, drivers.InstrumentError('refused')]):
                with self.assertRaises(drivers.InstrumentError):
                    io.measure(p)
            self.assertIn('CALC:STAT OFF', '\n'.join(e[3] for e in io.log.entries))
        finally:
            io.close()


class Logs(unittest.TestCase):
    def test_the_live_log_appends_every_command_on_the_real_bench_only(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(Path, 'home', lambda: Path(home)):
            live = V.LiveLog()
            live.add('>>', 'READ?', '8846A')
            f = Path(home) / '.calibration_suite' / 'command_log_live.txt'
            self.assertIn('READ?', f.read_text(encoding='utf-8'))
            f.unlink()
            virtual = V.virtualbench.mark_log(V.LiveLog())
            virtual.add('>>', 'READ?', '8846A')
            self.assertFalse(f.exists())                                                  # a demo session writes nothing

    def test_a_simulated_io_does_not_use_the_live_log(self):
        _b, io = make_io()
        try:
            self.assertNotIsInstance(io.log, V.LiveLog)
        finally:
            io.close()

    def test_the_waiting_text_names_the_last_command_on_the_wire(self):
        log = drivers.CommandLog()
        p = point('DCV')
        self.assertIn('starting', V.waiting_text(log, p, 1))
        log.add('>>', 'READ?', '8846A')
        self.assertIn('sent 8846A READ? - no reply yet', V.waiting_text(log, p, 12))
        log.add('<<', '+1.0E+00', '8846A')
        self.assertIn('got reply from 8846A', V.waiting_text(log, p, 13))


class WindowLookups(unittest.TestCase):
    def setUp(self):
        import qt_bench_harness as QH
        from PySide6.QtWidgets import QMainWindow
        self.hn = QH.QtHarness().start()
        self.root = QMainWindow()
        self.app = V.App(self.root, True)

    def tearDown(self):
        self.root.close()
        self.hn.stop()

    def test_a_point_is_found_by_its_id_although_the_zero_block_comes_first(self):
        self.assertNotEqual([p['id'] for p in V.POINTS], sorted(p['id'] for p in V.POINTS))      # the list is not in id order
        for p in (V.POINTS[0], V.POINTS[40], V.POINTS[-1]):
            self.assertIs(self.app.mo_point(str(p['id'])), p)

    def test_a_loaded_checkpoint_is_judged_again_and_results_of_deleted_points_are_dropped(self):
        p = point('DCV', zero_offset=False)
        self.app.found.clear(); self.app.left.clear()
        self.app.found.update({str(p['id']): dict(reading=p['nominal'] * 10, result='PASS'), '999': dict(reading=1.0, result='PASS')})
        self.app.left.update({str(p['id']): dict(reading=p['nominal'], result='FAIL')})
        self.app.rejudge_loaded()
        self.assertEqual(self.app.found[str(p['id'])]['result'], 'FAIL')                  # 10 x nominal is outside the limits
        self.assertNotIn('999', self.app.found)
        self.assertEqual(self.app.left[str(p['id'])]['result'], 'PASS')


if __name__ == '__main__':
    unittest.main()
