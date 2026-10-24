"""Stop on surprise, wired into the existing engines at the engine level (no driver and no shared file edited).

    python -m unittest tests.test_surprise_wiring

Per engine: the fault types of surprise.py are injected into a simulated bench (tests/surprise_faults.py) and the engine must
  * ask exactly ONE Stop / Continue question per surprise (Stop only where Continue is not safe), never repeat a write;
  * on Stop: raise SurpriseStop out of the engine's measuring routine so the engine's existing handler sends the outputs to standby / off;
  * on Continue: carry on and record the point as it always would, with the surprise in the command log;
  * on a CLEAN run: ask nothing, and produce the same command log, results, report rows and PDF bytes as the unguarded run;
  * in demo mode: never prompt.
tkinter is stubbed (tests/_tk_stub) for the App-level runs; the real Tk dialog is checked in tests/real_tk_surprise.py."""
import faulthandler
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'Procedures')]

import surprise  # noqa: E402
from surprise_faults import Dialog, FaultTransport, Rule  # noqa: E402

VH = h = None


def setUpModule():
    global VH, h
    import _tk_stub
    _tk_stub.install()
    import virtual_harness as _vh
    import handheld_dmm as _h
    VH, h = _vh, _vh.hh


def stable_log(io):
    """The command log without timestamps (a run's evidence), as text lines."""
    return [f'{inst}|{d}|{text}' for _t, inst, d, text in io.log.entries]


def surprise_lines(io):
    return [text for _t, _i, d, text in io.log.entries if d == '!!']


def report_bytes(app, header):
    """The Calibration Data PDF of a finished App run, byte-for-byte reproducible (fixed report date, invariant reportlab, no history written)."""
    import report_pdf
    from reportlab import rl_config
    rl_config.invariant = 1
    rows, _pts = app.certificate_rows_and_points()
    path = Path(tempfile.mkdtemp()) / 'r.pdf'
    report_pdf.write_calibration_pdf(str(path), rows, header=header, demo=app.any_synthetic(), details={}, issued_at='2026-01-01 00:00', record_history=False)
    return path.read_bytes(), json.dumps(rows, sort_keys=True, default=str)


def results_view(app):
    return {k: {f: v for f, v in r.items() if f != 'timestamp'} for k, r in sorted(app.results.items())}


class AppCase(unittest.TestCase):
    """Base for the App-level runs on the virtual bench with the guard forced on (a virtual log is otherwise never guarded)."""
    engine = None                      # set by the subclass

    def setUp(self):
        faulthandler.dump_traceback_later(240, exit=True)
        self.hn = VH.VHarness().start()
        self.dialog = Dialog()

    def tearDown(self):
        faulthandler.cancel_dump_traceback_later()
        self.hn.stop()
        for p in getattr(self, '_patches', []):
            p.stop()

    def patch(self, obj, name, value):
        p = mock.patch.object(obj, name, value)
        p.start()
        self._patches = getattr(self, '_patches', []) + [p]
        return p


class TestSurpriseWiringApi(unittest.TestCase):
    def test_demo_and_fast_demo_never_make_a_handler(self):
        """The App hands out a Stop / Continue dialog only for a real (non-demo) connection."""
        import truevolt_verification as T
        for demo, fast in ((True, False), (True, True)):
            app = T.App.__new__(T.App)
            app.demo, app._fast_demo = demo, fast
            with mock.patch.object(surprise, 'tk_handler', side_effect=AssertionError('a demo must not create a dialog')):
                self.assertIsNone(app._surprise_handler())

    def test_real_connection_makes_one_handler_per_window(self):
        import truevolt_verification as T
        app = T.App.__new__(T.App)
        app.demo = False
        app._fast_demo = False
        app.root = object()
        with mock.patch.object(surprise, 'tk_handler', return_value=lambda s: False) as tk:
            a = app._surprise_handler()
            b = app._surprise_handler()
        self.assertIs(a, b)
        tk.assert_called_once_with(app.root)


# =============================================================================================================================== Truevolt
class TruevoltIO(unittest.TestCase):
    """truevolt_verification.IO on the simulated bench, a fault injected into one transport."""
    MODEL = '34470A'

    def build(self, dmm_rules=(), cal_rules=(), dialog=None):
        import truevolt_verification as T
        from drivers.simulated import make_dmm_bench
        T.configure(self.MODEL)
        self.T = T
        _b, ft, dt = make_dmm_bench(self.MODEL)
        self.dt, self.ft = FaultTransport(dt, *dmm_rules), FaultTransport(ft, *cal_rules)
        io = T.IO('sim', 'sim', transports=(self.dt, self.ft), mods=None, virtual=True)       # virtual only for the short waits
        io.log.virtual = False                                                                # a real-run log: the guard is on without force
        if dialog is not None:
            io.enable_surprise(dialog)
        self.io = io
        return io

    def points(self, n=3):
        return [p for p in self.T.POINTS if p['source'] == 'calibrator' and p['terminal'] != 'REAR'][:n]

    # ---- clean ----
    def test_clean_run_asks_nothing_and_sends_the_same_commands(self):
        plain = self.build()
        r0 = [plain.measure(p) for p in self.points()]
        log0 = stable_log(plain)
        d = Dialog()
        io = self.build(dialog=d)
        self.assertEqual(len(io.guards), 2)
        r1 = [io.measure(p) for p in self.points()]
        self.assertEqual(r0, r1)
        self.assertEqual(stable_log(io), log0, 'guarded and unguarded runs must send exactly the same commands')
        self.assertEqual(d.count, 0)
        self.assertEqual(surprise_lines(io), [])

    def test_demo_log_is_never_guarded(self):
        io = self.build()
        io.log.virtual = True
        self.assertEqual(io.enable_surprise(Dialog()), [])

    # ---- (a) a bad reply ----
    def test_bad_read_reply_is_a_stop_only_surprise(self):
        for bad in ('', '=>', '?>', 'abc'):
            d = Dialog(True)                                       # the handler says Continue; the engine did not offer it
            io = self.build(dmm_rules=[Rule('READ?', bad, nth=2)], dialog=d)
            ps = self.points()
            io.measure(ps[0])
            with self.assertRaises(surprise.SurpriseStop):
                io.measure(ps[1])
            self.assertEqual(d.count, 1, bad)
            s = d.seen[0]
            self.assertEqual((s.kind, s.stop_only, s.command), ('reply', True, 'READ?'), bad)
            self.assertEqual(self.dt.queries.count('READ?'), 2, 'the read is not repeated')
            self.assertEqual(self.ft.writes.count('OPER'), 2, 'OPER once per point')
            io.standby()                                           # what the engine's worker does in its except block
            self.assertEqual(self.ft.writes[-1], 'STBY')
            self.assertTrue(any('Continue is not offered' in t for t in surprise_lines(io)))

    def test_calibrator_reply_problem_is_a_stop_only_surprise(self):
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('ERR?', '', nth=1)], dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        self.assertEqual((d.count, d.seen[0].kind, d.seen[0].stop_only), (1, 'reply', True))
        self.assertNotIn('OPER', self.ft.writes, 'the output is never enabled after an unreadable error queue')

    def test_one_timeout_is_retried_once_two_are_a_surprise(self):
        d = Dialog()
        io = self.build(dmm_rules=[Rule('READ?', timeout=True, nth=1, times=1)], dialog=d)
        v = io.measure(self.points(1)[0])
        self.assertAlmostEqual(v, 0.1, places=5)
        self.assertEqual(d.count, 0)
        self.assertEqual(self.dt.queries.count('READ?'), 2, 'one read-only retry')
        self.assertEqual(self.ft.writes.count('OPER'), 1, 'the calibrator write is not repeated')
        d2 = Dialog()
        io = self.build(dmm_rules=[Rule('READ?', timeout=True, nth=1, times=2)], dialog=d2)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        self.assertEqual((d2.count, d2.seen[0].reply, d2.seen[0].stop_only), (1, '', True))
        self.assertEqual(self.dt.queries.count('READ?'), 2)

    # ---- (c) error queue after a write ----
    def test_dmm_error_queue_after_configure_stop(self):
        d = Dialog(False)
        io = self.build(dmm_rules=[Rule('SYST:ERR?', '-113,"Undefined header"', after='VOLT:DC:NPLC')], dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        s = d.seen[0]
        self.assertEqual((d.count, s.kind, s.stop_only), (1, 'errqueue', False))
        self.assertIn('-113', s.reply)
        self.assertEqual([w for w in self.ft.writes if w.startswith('OUT')], [], 'no output was set after the surprise')
        self.assertNotIn('OPER', self.ft.writes)
        self.assertEqual(self.dt.writes.count('VOLT:DC:NPLC 10'), 1, 'no write repeated')
        io.standby()
        self.assertEqual(self.ft.writes[-1], 'STBY')

    def test_dmm_error_queue_after_configure_continue_records_the_point_as_usual(self):
        d = Dialog(True)
        io = self.build(dmm_rules=[Rule('SYST:ERR?', '-113,"Undefined header"', after='VOLT:DC:NPLC')], dialog=d)
        p = self.points(1)[0]
        v = io.measure(p)
        clean = self.build()
        self.assertEqual(v, clean.measure(p), 'the point is measured and returned exactly as in a clean run')
        lines = surprise_lines(io)
        self.assertTrue(any('SURPRISE errqueue' in t for t in lines))
        self.assertTrue(any('operator chose Continue' in t for t in lines))
        self.assertEqual(d.count, 1)

    def test_calibrator_error_queue_after_output_is_stop_only_and_never_operates(self):
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('ERR?', '-222,"Data out of range"', after='OUT')], dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        s = d.seen[0]
        self.assertEqual((d.count, s.kind, s.stop_only), (1, 'errqueue', True))
        self.assertNotIn('OPER', self.ft.writes)
        self.assertEqual(sum(1 for w in self.ft.writes if w.startswith('OUT')), 1, 'the OUT is not repeated')
        io.standby()
        self.assertEqual(self.ft.writes[-1], 'STBY')

    # ---- (b) read-back: the only confirmations in this engine are the calibrator's standby / operate states ----
    def test_standby_not_confirmed_is_still_a_hard_stop_with_no_dialog(self):
        import reset_startup
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('OPER?', '1', after='STBY')], dialog=d)
        with self.assertRaises(reset_startup.ResetFailed):
            io.reset_at_start()
        self.assertEqual(d.count, 0, 'a safe state that cannot be confirmed is a safety stop, never a Continue question')

    def test_unreadable_standby_confirmation_is_a_stop_only_surprise(self):
        import reset_startup
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('OPER?', '', after='STBY')], dialog=d)
        with self.assertRaises(reset_startup.ResetFailed):
            io.reset_at_start()
        self.assertEqual((d.count, d.seen[0].stop_only), (1, True))


class TruevoltIO34460A(TruevoltIO):
    MODEL = '34460A'


class TruevoltIO34461A(TruevoltIO):
    MODEL = '34461A'


class TruevoltIO34465A(TruevoltIO):
    MODEL = '34465A'


class TruevoltApp(AppCase):
    """The whole App on the virtual bench (stubbed Tk), the guard forced on."""
    MODEL = '34470A'
    HEADER = [('Instrument', 'Keysight 34470A'), ('Instrument ID', 'A1'), ('Serial', 'S1')]

    def make(self, dmm_rules=(), cal_rules=(), guard=True):
        import truevolt_verification as T
        import virtualbench
        T.messagebox = h.messagebox
        dialog = self.dialog
        real_pair = virtualbench.dmm_pair

        def pair(model, cal='5560A'):
            bench, ft, dt = real_pair(model, cal)
            return bench, FaultTransport(ft, *cal_rules), FaultTransport(dt, *dmm_rules)
        self.patch(virtualbench, 'dmm_pair', pair)
        if guard:
            orig = T.IO

            class Guarded(orig):
                def __init__(self, *a, **k):
                    super().__init__(*a, **k)
                    self.enable_surprise(dialog, force=True)          # force: a virtual (demo) log is otherwise never guarded
            self.patch(T, 'IO', Guarded)
        app = T.App(self.hn.root, self.MODEL, demo=True, fast_demo=False)
        app.asset.set('A1')
        app.serial.set('S1')
        self.hn.app = app
        return app

    def restart(self, dialog=None):
        self.hn.stop()
        for p in getattr(self, '_patches', []):
            p.stop()
        self._patches = []
        self.hn = VH.VHarness().start()
        self.dialog = dialog or Dialog()

    def test_clean_run_is_identical_with_and_without_the_guard(self):
        app0 = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        ref = (stable_log(app0.io), results_view(app0), report_bytes(app0, self.HEADER), VH.wire(app0.io))
        self.restart()
        app1 = self.make(guard=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 0, 'a clean run asks nothing')
        self.assertTrue(app1.io.guards, 'the guard really was on')
        got = (stable_log(app1.io), results_view(app1), report_bytes(app1, self.HEADER), VH.wire(app1.io))
        self.assertEqual(got[0], ref[0], 'same command log')
        self.assertEqual(got[1], ref[1], 'same results')
        self.assertEqual(got[2][1], ref[2][1], 'same report rows')
        self.assertEqual(got[2][0], ref[2][0], 'same PDF bytes')
        self.assertEqual(got[3], ref[3])

    def test_a_real_connection_wires_the_guard_with_the_apps_handler(self):
        """Test connections on a NON-demo window (VISA replaced by the simulated transports): the IO it builds has both guards, with the window's handler."""
        import truevolt_verification as T
        from drivers.simulated import make_dmm_bench
        T.messagebox = h.messagebox
        _b, ft, dt = make_dmm_bench(self.MODEL)
        self.patch(T.drivers, 'open_visa', lambda addr, **k: dt if addr.upper().startswith('USB') else ft)
        app = T.App(self.hn.root, self.MODEL, demo=False, fast_demo=False)
        self.hn.app = app
        self.patch(app, '_surprise_handler', lambda: self.dialog)
        app.test_connections()
        self.assertIsNotNone(app.io)
        self.assertEqual([g.handler for g in app.io.guards], [self.dialog, self.dialog])
        self.assertFalse(app.io.log.virtual)

    def test_demo_without_the_forced_guard_never_prompts(self):
        with mock.patch.object(surprise, 'tk_handler', side_effect=AssertionError('demo must not build a dialog')):
            app = self.make(guard=False)
            self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 0)
        self.assertTrue(app.io.log.virtual)
        self.assertEqual(app.io.guards, [])

    def test_stop_on_a_bad_read_goes_through_the_engines_standby_and_error_dialog(self):
        app = self.make(dmm_rules=[Rule('READ?', '=>', nth=3)])
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 1)
        self.assertEqual(len(app.results), 2, 'the two points before the surprise are recorded, the third is not')
        self.assertFalse(app.busy)
        self.assertTrue(self.hn.boxes('showerror'), 'the engine shows its own error dialog')
        self.assertEqual(VH.wire(app.io)[-1], ('5560A', 'STBY'), 'outputs end in standby')
        self.assertTrue(any('SURPRISE reply' in t for t in surprise_lines(app.io)))

    def test_writes_are_never_repeated_after_a_surprise(self):
        clean = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        clean_wire = VH.wire(clean.io)
        self.restart()
        app = self.make(dmm_rules=[Rule('READ?', '', nth=3)])
        self.assertTrue(self.hn.run_all())
        wire = VH.wire(app.io)
        k = len(wire) - 1                                             # the final STBY of the engine's except block
        self.assertEqual(wire[:k], clean_wire[:k], 'up to the surprise the run sent exactly what the clean run sent; nothing was repeated')

    def test_continue_on_a_dmm_error_queue_entry_records_every_point_like_a_clean_run(self):
        clean = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        ref = results_view(clean)
        self.restart(Dialog(True))
        app = self.make(dmm_rules=[Rule('SYST:ERR?', '-113,"Undefined header"', after='VOLT:DC:NPLC', nth=4)])
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 1)
        self.assertEqual(results_view(app), ref, 'Continue: the point is recorded exactly as it would have been')
        self.assertFalse(self.hn.boxes('showerror'))
        self.assertTrue(any('operator chose Continue' in t for t in surprise_lines(app.io)))


# =============================================================================================================================== 34970A / 34972A
class DacqIO(unittest.TestCase):
    """dacq_verification.IO on the simulated bench.  The DMM's SYST:ERR? is asked at connect (1), after CONF (2) and after the reading (3) of the first point."""
    MODEL = '34970A'
    CAL = 'Fluke 5560A'

    def build(self, dmm_rules=(), cal_rules=(), dialog=None):
        import dacq_verification as D
        from drivers.simulated import make_dacq_bench
        D.configure(self.MODEL)
        self.D = D
        _b, ft, dt = make_dacq_bench(self.MODEL, D.CALIBRATORS[self.CAL][0], {2: '34901A'})
        self.dt, self.ft = FaultTransport(dt, *dmm_rules), FaultTransport(ft, *cal_rules)
        io = D.IO('sim', 'sim', self.CAL, 9600, '34901A', 2, transports=(self.dt, self.ft), mods=None, virtual=True)
        io.log.virtual = False
        if dialog is not None:
            io.enable_surprise(dialog)
        self.io = io
        return io

    def points(self, n=3):
        return [p for p in self.D.POINTS if p['source'] == 'calibrator'][:n]

    def test_clean_run_asks_nothing_and_sends_the_same_commands(self):
        plain = self.build()
        r0 = [plain.measure(p) for p in self.points()]
        log0 = stable_log(plain)
        d = Dialog()
        io = self.build(dialog=d)
        self.assertEqual(len(io.guards), 2)
        r1 = [io.measure(p) for p in self.points()]
        self.assertEqual(r0, r1)
        self.assertEqual(stable_log(io), log0)
        self.assertEqual((d.count, surprise_lines(io)), (0, []))

    def test_demo_log_is_never_guarded(self):
        io = self.build()
        io.log.virtual = True
        self.assertEqual(io.enable_surprise(Dialog()), [])

    def test_bad_read_reply_is_a_stop_only_surprise(self):
        for bad in ('', '=>', '?>', 'abc'):
            d = Dialog(True)
            io = self.build(dmm_rules=[Rule('READ?', bad, nth=2)], dialog=d)
            ps = self.points()
            io.measure(ps[0])
            with self.assertRaises(surprise.SurpriseStop):
                io.measure(ps[1])
            self.assertEqual(d.count, 1, bad)
            self.assertEqual((d.seen[0].kind, d.seen[0].stop_only, d.seen[0].command), ('reply', True, 'READ?'), bad)
            self.assertEqual(self.dt.queries.count('READ?'), 2)
            self.assertEqual(self.ft.writes.count('OPER'), 2, 'OPER once per point')
            io.standby()
            self.assertEqual(self.ft.writes[-1], 'STBY')

    def test_one_timeout_is_retried_once_two_are_a_surprise(self):
        d = Dialog()
        io = self.build(dmm_rules=[Rule('READ?', timeout=True, nth=1, times=1)], dialog=d)
        self.assertAlmostEqual(io.measure(self.points(1)[0]), -10.0, places=3)
        self.assertEqual((d.count, self.dt.queries.count('READ?'), self.ft.writes.count('OPER')), (0, 2, 1))
        d2 = Dialog()
        io = self.build(dmm_rules=[Rule('READ?', timeout=True, nth=1, times=2)], dialog=d2)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        self.assertEqual((d2.count, d2.seen[0].reply, d2.seen[0].stop_only), (1, '', True))

    def test_dmm_error_queue_after_configure_stop_and_continue(self):
        rule = lambda: [Rule('SYST:ERR?', '-113,"Undefined header"', nth=2)]          # the 2nd ask is the check after CONF of point 1
        d = Dialog(False)
        io = self.build(dmm_rules=rule(), dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        s = d.seen[0]
        self.assertEqual((d.count, s.kind, s.stop_only, s.command), (1, 'errqueue', False, 'SYST:ERR?'))
        self.assertIn('-113', s.reply)
        self.assertEqual([w for w in self.ft.writes if w.startswith('OUT')], [])
        self.assertNotIn('OPER', self.ft.writes)
        io.standby()
        self.assertEqual(self.ft.writes[-1], 'STBY')
        d = Dialog(True)
        io = self.build(dmm_rules=rule(), dialog=d)
        p = self.points(1)[0]
        v = io.measure(p)
        self.assertEqual(v, self.build().measure(p), 'Continue: the point is measured exactly as in a clean run')
        self.assertEqual(sum(1 for w in self.ft.writes if w.startswith('OUT')), 1, 'the OUT is sent once')
        self.assertTrue(any('operator chose Continue' in t for t in surprise_lines(io)))

    def test_dmm_error_queue_after_the_reading_continue_keeps_the_reading(self):
        d = Dialog(True)
        io = self.build(dmm_rules=[Rule('SYST:ERR?', '-221,"Settings conflict"', nth=3)], dialog=d)       # the check after READ? of point 1
        p = self.points(1)[0]
        v = io.measure(p)
        self.assertAlmostEqual(v, -10.0, places=3)
        self.assertEqual((d.count, d.seen[0].kind, d.seen[0].stop_only), (1, 'errqueue', False))
        self.assertEqual(self.ft.writes[-1], 'STBY', 'the output was already in standby')

    def test_error_queue_with_several_entries_shows_the_entries_not_the_final_no_error(self):
        d = Dialog(False)
        io = self.build(dmm_rules=[Rule('SYST:ERR?', '-113,"Undefined header"', nth=2), Rule('SYST:ERR?', '-221,"Settings conflict"', nth=3)], dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        self.assertIn('-113', d.seen[0].reply)
        self.assertIn('-221', d.seen[0].reply)
        self.assertNotIn('No error', d.seen[0].reply)

    def test_calibrator_error_queue_after_output_is_stop_only_and_never_operates(self):
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('ERR?', '-222,"Data out of range"', after='OUT')], dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        s = d.seen[0]
        self.assertEqual((d.count, s.kind, s.stop_only), (1, 'errqueue', True))
        self.assertNotIn('OPER', self.ft.writes)
        self.assertEqual(sum(1 for w in self.ft.writes if w.startswith('OUT')), 1)
        io.standby()
        self.assertEqual(self.ft.writes[-1], 'STBY')

    def test_standby_not_confirmed_is_still_a_hard_stop_with_no_dialog(self):
        import reset_startup
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('OPER?', '1', after='STBY')], dialog=d)
        with self.assertRaises(reset_startup.ResetFailed):
            io.reset_at_start()
        self.assertEqual(d.count, 0)


class DacqIO34972A(DacqIO):
    MODEL = '34972A'


class DacqIO5522A(DacqIO):
    CAL = 'Fluke 5522A'


class DacqApp(AppCase):
    MODEL = '34970A'
    HEADER = [('Instrument', 'Keysight 34970A'), ('Instrument ID', 'A1'), ('Serial', 'S1')]

    def make(self, dmm_rules=(), cal_rules=(), guard=True):
        import dacq_verification as D
        import virtualbench
        D.configure(self.MODEL)
        D.messagebox = h.messagebox
        dialog = self.dialog
        real_pair = virtualbench.dacq_pair

        def pair(model, cal='5560A', modules=None):
            bench, ft, dt = real_pair(model, cal, modules)
            return bench, FaultTransport(ft, *cal_rules), FaultTransport(dt, *dmm_rules)
        self.patch(virtualbench, 'dacq_pair', pair)
        if guard:
            orig = D.IO

            class Guarded(orig):
                def __init__(self, *a, **k):
                    super().__init__(*a, **k)
                    self.enable_surprise(dialog, force=True)
            self.patch(D, 'IO', Guarded)
        app = D.App(self.hn.root, self.MODEL, demo=True, fast_demo=False)
        app.asset.set('A1')
        app.serial.set('S1')
        self.hn.app = app
        return app

    restart = TruevoltApp.restart

    def test_clean_run_is_identical_with_and_without_the_guard(self):
        app0 = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        ref = (stable_log(app0.io), results_view(app0), report_bytes(app0, self.HEADER), VH.wire(app0.io))
        self.restart()
        app1 = self.make(guard=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 0)
        self.assertTrue(app1.io.guards)
        got = (stable_log(app1.io), results_view(app1), report_bytes(app1, self.HEADER), VH.wire(app1.io))
        self.assertEqual(got[0], ref[0])
        self.assertEqual(got[1], ref[1])
        self.assertEqual(got[2][1], ref[2][1], 'same report rows')
        self.assertEqual(got[2][0], ref[2][0], 'same PDF bytes')
        self.assertEqual(got[3], ref[3])

    def test_a_real_connection_wires_the_guard_with_the_apps_handler(self):
        import dacq_verification as D
        from drivers.simulated import make_dacq_bench
        D.configure(self.MODEL)
        D.messagebox = h.messagebox
        _b, ft, dt = make_dacq_bench(self.MODEL, '5560A', {2: '34901A'})
        self.patch(D.drivers, 'open_visa', lambda addr, **k: dt if addr.upper().startswith('ASRL') and '9' not in addr else ft)
        app = D.App(self.hn.root, self.MODEL, demo=False, fast_demo=False)
        self.hn.app = app
        self.patch(app, '_surprise_handler', lambda: self.dialog)
        app.dmm_addr.set('COM1')
        app.cal_addr.set('COM9')
        app.test_connections()
        self.assertIsNotNone(app.io)
        self.assertEqual([g.handler for g in app.io.guards], [self.dialog, self.dialog])
        self.assertFalse(app.io.log.virtual)

    def test_demo_without_the_forced_guard_never_prompts(self):
        with mock.patch.object(surprise, 'tk_handler', side_effect=AssertionError('demo must not build a dialog')):
            app = self.make(guard=False)
            self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 0)
        self.assertEqual(app.io.guards, [])

    def test_demo_and_fast_demo_never_make_a_handler(self):
        import dacq_verification as D
        for demo, fast in ((True, False), (True, True)):
            app = D.App.__new__(D.App)
            app.demo, app._fast_demo = demo, fast
            with mock.patch.object(surprise, 'tk_handler', side_effect=AssertionError):
                self.assertIsNone(app._surprise_handler())
        app = D.App.__new__(D.App)
        app.demo, app._fast_demo, app.root = False, False, object()
        with mock.patch.object(surprise, 'tk_handler', return_value=lambda s: False) as tk:
            self.assertIs(app._surprise_handler(), app._surprise_handler())
        tk.assert_called_once_with(app.root)

    def test_stop_on_a_bad_read_goes_through_the_engines_standby_and_error_dialog(self):
        app = self.make(dmm_rules=[Rule('READ?', '=>', nth=3)])
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 1)
        self.assertLess(len(app.results), 3 + 1)
        self.assertFalse(app.busy)
        self.assertTrue(self.hn.boxes('showerror'))
        self.assertEqual(VH.wire(app.io)[-1], ('5560A', 'STBY'))

    def test_writes_are_never_repeated_after_a_surprise(self):
        clean = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        clean_wire = VH.wire(clean.io)
        self.restart()
        app = self.make(dmm_rules=[Rule('READ?', '', nth=3)])
        self.assertTrue(self.hn.run_all())
        wire = VH.wire(app.io)
        k = len(wire) - 1
        self.assertEqual(wire[:k], clean_wire[:k])

    def test_continue_on_a_dmm_error_queue_entry_records_every_point_like_a_clean_run(self):
        clean = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        ref = results_view(clean)
        self.restart(Dialog(True))
        app = self.make(dmm_rules=[Rule('SYST:ERR?', '-113,"Undefined header"', nth=5)])
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 1)
        self.assertEqual(results_view(app), ref)
        self.assertFalse(self.hn.boxes('showerror'))


# =============================================================================================================================== 34410A / 34411A
class A34410IO(unittest.TestCase):
    """agilent34410a_verification.IO on the simulated bench.  The meter's SYST:ERR? is asked at connect (1), after the configuration (2) and after the reading (3)
    of the first point."""
    MODEL = '34410A'
    CAL = 'Fluke 5560A'

    def build(self, dmm_rules=(), cal_rules=(), dialog=None):
        import agilent34410a_verification as A
        from drivers.simulated_34410a import make_34410a_bench
        A.configure(self.MODEL)
        self.A = A
        _b, ft, dt = make_34410a_bench(A.CALIBRATORS[self.CAL][0], 'GPIB', self.MODEL)
        self.dt, self.ft = FaultTransport(dt, *dmm_rules), FaultTransport(ft, *cal_rules)
        io = A.IO('sim', 'sim', self.CAL, 9600, 'GPIB', transports=(self.dt, self.ft), mods=None, virtual=True)
        io.log.virtual = False
        if dialog is not None:
            io.enable_surprise(dialog)
        self.io = io
        return io

    def points(self, n=3):
        return [p for p in self.A.POINTS if p['source'] == 'calibrator' and p['terminal'] != 'REAR' and p['kind'] in ('DCV', 'DCI', 'ACV')][:n]

    def test_clean_run_asks_nothing_and_sends_the_same_commands(self):
        plain = self.build()
        r0 = [plain.measure(p) for p in self.points()]
        log0 = stable_log(plain)
        d = Dialog()
        io = self.build(dialog=d)
        self.assertEqual(len(io.guards), 2)
        r1 = [io.measure(p) for p in self.points()]
        self.assertEqual(r0, r1)
        self.assertEqual(stable_log(io), log0)
        self.assertEqual((d.count, surprise_lines(io)), (0, []))

    def test_demo_log_is_never_guarded(self):
        io = self.build()
        io.log.virtual = True
        self.assertEqual(io.enable_surprise(Dialog()), [])

    def test_bad_read_reply_is_a_stop_only_surprise(self):
        for bad in ('', '=>', '?>', 'abc'):
            d = Dialog(True)
            io = self.build(dmm_rules=[Rule('READ?', bad, nth=2)], dialog=d)
            ps = self.points()
            io.measure(ps[0])
            with self.assertRaises(surprise.SurpriseStop):
                io.measure(ps[1])
            self.assertEqual(d.count, 1, bad)
            self.assertEqual((d.seen[0].kind, d.seen[0].stop_only, d.seen[0].command), ('reply', True, 'READ?'), bad)
            self.assertEqual(self.dt.queries.count('READ?'), 2)
            self.assertEqual(self.ft.writes.count('OPER'), 2)
            self.assertEqual(self.ft.writes[-1], 'STBY', "the engine's own finally: put the calibrator in standby")

    def test_one_timeout_is_retried_once_two_are_a_surprise(self):
        d = Dialog()
        io = self.build(dmm_rules=[Rule('READ?', timeout=True, nth=1, times=1)], dialog=d)
        io.measure(self.points(1)[0])
        self.assertEqual((d.count, self.dt.queries.count('READ?'), self.ft.writes.count('OPER')), (0, 2, 1))
        d2 = Dialog()
        io = self.build(dmm_rules=[Rule('READ?', timeout=True, nth=1, times=2)], dialog=d2)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        self.assertEqual((d2.count, d2.seen[0].reply, d2.seen[0].stop_only), (1, '', True))

    # ---- (b) read-back mismatch: the meter's set / read back / compare of the configuration ----
    def test_readback_mismatch_of_the_configuration_is_a_stop_only_surprise(self):
        cases = (('SENS:FUNC?', '"VOLT:AC"'), ('SENS:VOLT:DC:RANG?', '+5.000000E+00'), ('SENS:VOLT:DC:RANG:AUTO?', '1'), ('SENS:VOLT:DC:NPLC?', '+1.000000E+01'))
        for query, bad in cases:
            d = Dialog(True)
            io = self.build(dmm_rules=[Rule(query, bad)], dialog=d)
            p = self.points(1)[0]                                                    # a DC volts point
            with self.assertRaises(surprise.SurpriseStop):
                io.measure(p)
            s = d.seen[0]
            self.assertEqual((d.count, s.kind, s.stop_only, s.command, s.reply), (1, 'readback', True, query, bad), query)
            self.assertEqual([w for w in self.dt.writes if w.startswith('CONF:')], ['CONF:VOLT:DC 0.1'], 'the write is sent once, never repeated')
            self.assertEqual([w for w in self.ft.writes if w.startswith('OUT')], [], 'no output after a configuration that did not read back')
            self.assertNotIn('OPER', self.ft.writes)
            self.assertEqual(self.ft.writes[-1], 'STBY')
            self.assertTrue(any('SURPRISE readback' in t for t in surprise_lines(io)))

    def test_without_the_guard_a_readback_mismatch_still_raises_as_before(self):
        io = self.build(dmm_rules=[Rule('SENS:VOLT:DC:RANG?', '+5.000000E+00')])
        with self.assertRaises(self.A.drivers.InstrumentError) as cm:
            io.measure(self.points(1)[0])
        self.assertNotIsInstance(cm.exception, surprise.SurpriseStop)

    # ---- (c) error queue after a write ----
    def test_dmm_error_queue_after_configure_stop_and_continue(self):
        rule = lambda: [Rule('SYST:ERR?', '-113,"Undefined header"', nth=2)]
        d = Dialog(False)
        io = self.build(dmm_rules=rule(), dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        s = d.seen[0]
        self.assertEqual((d.count, s.kind, s.stop_only), (1, 'errqueue', False))
        self.assertIn('-113', s.reply)
        self.assertEqual([w for w in self.ft.writes if w.startswith('OUT')], [])
        self.assertEqual(self.ft.writes[-1], 'STBY')
        d = Dialog(True)
        io = self.build(dmm_rules=rule(), dialog=d)
        p = self.points(1)[0]
        self.assertEqual(io.measure(p), self.build().measure(p), 'Continue: measured exactly as in a clean run')
        self.assertEqual(sum(1 for w in self.ft.writes if w.startswith('OUT')), 1)
        self.assertTrue(any('operator chose Continue' in t for t in surprise_lines(io)))

    def test_dmm_error_queue_after_the_reading_continue_keeps_the_reading(self):
        d = Dialog(True)
        io = self.build(dmm_rules=[Rule('SYST:ERR?', '-221,"Settings conflict"', nth=3)], dialog=d)
        p = self.points(1)[0]
        v = io.measure(p)
        self.assertEqual(v, self.build().measure(p))
        self.assertEqual((d.count, d.seen[0].kind, d.seen[0].stop_only), (1, 'errqueue', False))
        self.assertEqual(self.ft.writes[-1], 'STBY')

    def test_unreadable_error_queue_is_a_stop_only_bad_reply(self):
        d = Dialog(True)
        io = self.build(dmm_rules=[Rule('SYST:ERR?', '', nth=2, times=30)], dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        self.assertEqual((d.count, d.seen[0].kind, d.seen[0].stop_only), (1, 'reply', True))
        self.assertEqual([w for w in self.ft.writes if w.startswith('OUT')], [])

    def test_calibrator_error_queue_after_output_is_stop_only_and_never_operates(self):
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('ERR?', '-222,"Data out of range"', after='OUT')], dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.points(1)[0])
        s = d.seen[0]
        self.assertEqual((d.count, s.kind, s.stop_only), (1, 'errqueue', True))
        self.assertNotIn('OPER', self.ft.writes)
        self.assertEqual(sum(1 for w in self.ft.writes if w.startswith('OUT')), 1)
        self.assertEqual(self.ft.writes[-1], 'STBY')

    def test_standby_not_confirmed_is_still_a_hard_stop_with_no_dialog(self):
        import reset_startup
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('OPER?', '1', after='STBY')], dialog=d)
        with self.assertRaises(reset_startup.ResetFailed):
            io.reset_at_start()
        self.assertEqual(d.count, 0)


class A34411IO(A34410IO):
    MODEL = '34411A'


class A34410IO5522A(A34410IO):
    """The 5522A as the source: its ZCOMP set / read back / compare (resistance points) is the second read-back of this engine."""
    CAL = 'Fluke 5522A'

    def ohm_point(self):
        return [p for p in self.A.POINTS if p['kind'] == 'OHM4' and p['source'] == 'calibrator'][0]

    def test_zcomp_readback_mismatch_is_a_stop_only_surprise(self):
        d = Dialog(True)
        io = self.build(cal_rules=[Rule('ZCOMP?', 'NONE')], dialog=d)
        with self.assertRaises(surprise.SurpriseStop):
            io.measure(self.ohm_point())
        s = d.seen[0]
        self.assertEqual((d.count, s.kind, s.stop_only, s.command, s.reply), (1, 'readback', True, 'ZCOMP?', 'NONE'))
        self.assertEqual(self.ft.writes.count('ZCOMP WIRE4'), 1, 'sent once, never repeated')
        self.assertNotIn('OPER', self.ft.writes)
        self.assertEqual(self.ft.writes[-1], 'STBY')

    def test_zcomp_clean(self):
        d = Dialog()
        io = self.build(dialog=d)
        self.assertAlmostEqual(io.measure(self.ohm_point()), 100.0, delta=0.01)
        self.assertEqual(d.count, 0)
        self.assertIn('ZCOMP WIRE4', self.ft.writes)


class A34410App(AppCase):
    MODEL = '34410A'
    HEADER = [('Instrument', 'Keysight 34410A'), ('Instrument ID', 'A1'), ('Serial', 'S1')]

    def make(self, dmm_rules=(), cal_rules=(), guard=True):
        import agilent34410a_verification as A
        import drivers.simulated_34410a as sim
        A.configure(self.MODEL)
        A.messagebox = h.messagebox
        dialog = self.dialog
        real = sim.make_34410a_bench

        def bench(cal='5522A', bus='GPIB', model='34410A'):
            b, ft, dt = real(cal, bus, model)
            return b, FaultTransport(ft, *cal_rules), FaultTransport(dt, *dmm_rules)
        self.patch(sim, 'make_34410a_bench', bench)
        if guard:
            orig = A.IO

            class Guarded(orig):
                def __init__(self, *a, **k):
                    super().__init__(*a, **k)
                    self.enable_surprise(dialog, force=True)
            self.patch(A, 'IO', Guarded)
        app = A.App(self.hn.root, demo=True, fast_demo=False)
        app.asset.set('A1')
        app.serial.set('S1')
        self.hn.app = app
        return app

    restart = TruevoltApp.restart

    def test_clean_run_is_identical_with_and_without_the_guard(self):
        app0 = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        ref = (stable_log(app0.io), results_view(app0), report_bytes(app0, self.HEADER), VH.wire(app0.io))
        self.restart()
        app1 = self.make(guard=True)
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 0)
        self.assertTrue(app1.io.guards)
        got = (stable_log(app1.io), results_view(app1), report_bytes(app1, self.HEADER), VH.wire(app1.io))
        self.assertEqual(got[0], ref[0])
        self.assertEqual(got[1], ref[1])
        self.assertEqual(got[2][1], ref[2][1], 'same report rows')
        self.assertEqual(got[2][0], ref[2][0], 'same PDF bytes')
        self.assertEqual(got[3], ref[3])

    def test_a_real_connection_wires_the_guard_with_the_apps_handler(self):
        import agilent34410a_verification as A
        from drivers.simulated_34410a import make_34410a_bench
        A.configure(self.MODEL)
        A.messagebox = h.messagebox
        _b, ft, dt = make_34410a_bench('5560A', 'GPIB', self.MODEL)
        self.patch(A.drivers, 'open_visa', lambda addr, **k: ft if addr.upper().startswith('ASRL') else dt)
        app = A.App(self.hn.root, demo=False, fast_demo=False)
        self.hn.app = app
        self.patch(app, '_surprise_handler', lambda: self.dialog)
        app.test_connections()
        self.assertIsNotNone(app.io)
        self.assertEqual([g.handler for g in app.io.guards], [self.dialog, self.dialog])
        self.assertFalse(app.io.log.virtual)

    def test_demo_without_the_forced_guard_never_prompts(self):
        with mock.patch.object(surprise, 'tk_handler', side_effect=AssertionError('demo must not build a dialog')):
            app = self.make(guard=False)
            self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 0)
        self.assertEqual(app.io.guards, [])

    def test_demo_and_fast_demo_never_make_a_handler(self):
        import agilent34410a_verification as A
        for demo, fast in ((True, False), (True, True)):
            app = A.App.__new__(A.App)
            app.demo, app._fast_demo = demo, fast
            with mock.patch.object(surprise, 'tk_handler', side_effect=AssertionError):
                self.assertIsNone(app._surprise_handler())
        app = A.App.__new__(A.App)
        app.demo, app._fast_demo, app.root = False, False, object()
        with mock.patch.object(surprise, 'tk_handler', return_value=lambda s: False) as tk:
            self.assertIs(app._surprise_handler(), app._surprise_handler())
        tk.assert_called_once_with(app.root)

    def test_stop_on_a_readback_mismatch_goes_through_the_engines_standby_and_error_dialog(self):
        app = self.make(dmm_rules=[Rule('SENS:FUNC?', '"VOLT:AC"', nth=3)])
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 1)
        self.assertFalse(app.busy)
        self.assertTrue(self.hn.boxes('showerror'))
        self.assertEqual(VH.wire(app.io)[-1], ('5560A', 'STBY'))
        self.assertEqual(self.dialog.seen[0].kind, 'readback')

    def test_writes_are_never_repeated_after_a_surprise(self):
        clean = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        clean_wire = VH.wire(clean.io)
        self.restart()
        app = self.make(dmm_rules=[Rule('READ?', '', nth=3)])
        self.assertTrue(self.hn.run_all())
        wire = VH.wire(app.io)
        while wire and wire[-1] == ('5560A', 'STBY'):          # this engine's own finally and its worker's except block both put the calibrator in standby
            wire.pop()
        self.assertEqual(wire, clean_wire[:len(wire)], 'up to the surprise the run sent exactly what the clean run sent; nothing was repeated')
        self.assertEqual(VH.wire(app.io)[-1], ('5560A', 'STBY'))

    def test_continue_on_a_dmm_error_queue_entry_records_every_point_like_a_clean_run(self):
        clean = self.make(guard=False)
        self.assertTrue(self.hn.run_all())
        ref = results_view(clean)
        self.restart(Dialog(True))
        app = self.make(dmm_rules=[Rule('SYST:ERR?', '-113,"Undefined header"', nth=5)])
        self.assertTrue(self.hn.run_all())
        self.assertEqual(self.dialog.count, 1)
        self.assertEqual(results_view(app), ref)
        self.assertFalse(self.hn.boxes('showerror'))


class A34411App(A34410App):
    MODEL = '34411A'
    HEADER = [('Instrument', 'Keysight 34411A'), ('Instrument ID', 'A1'), ('Serial', 'S1')]


# =============================================================================================================================== real Tk
class RealTkEngines(unittest.TestCase):
    """The real engine window on a real Tk 9 under Xvfb, a worker thread and mainloop (tests/real_tk_surprise_engine.py)."""
    ENGINES = ('truevolt', 'dacq', 'a34410')

    def run_one(self, engine, scenario):
        import os
        import shutil
        import subprocess
        import glob
        # The engines' worker threads call root.after(...) themselves (existing code).  On the uv Python 3.12 / Tk 9.0.3 build in the sandbox that call never
        # runs (a thread-support quirk of that build, not of the wiring), so prefer the newest Python that has tkinter.
        cands = sorted(glob.glob(str(Path.home() / '.local/share/uv/python/*/bin/python3')), reverse=True) + [sys.executable]
        py = None
        for c in cands:
            try:
                if subprocess.run([c, '-c', 'import tkinter'], capture_output=True, timeout=60).returncode == 0:
                    py = c
                    break
            except (OSError, subprocess.SubprocessError):
                pass
        if py is None:
            self.skipTest('no Python with tkinter')
        cmd = [py, str(ROOT / 'tests' / 'real_tk_surprise_engine.py'), engine, scenario]
        if not os.environ.get('DISPLAY'):
            xvfb = shutil.which('xvfb-run')
            if not xvfb:
                self.skipTest('no display and no xvfb-run')
            cmd = [xvfb, '-a', '-s', '-screen 0 1280x800x24'] + cmd
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + '\n' + r.stderr[-3000:])
        self.assertIn('ALL OK', r.stdout)

    def test_every_wired_engine_on_a_real_tk(self):
        for engine in self.ENGINES:
            for scenario in ('clean', 'stop', 'continue'):
                with self.subTest(engine=engine, scenario=scenario):
                    self.run_one(engine, scenario)


if __name__ == '__main__':
    unittest.main()
