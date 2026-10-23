"""Fluke 8808A: prompt-tolerant replies (real-bench failure: '*OPC? << =>' then '*ESR? << =>' after *RST, Echo set OFF at the front panel).

Reply handling only; no command, limit, pass/fail rule or safety prompt is touched. What is checked, on the simulated bench:
  * the failing sequence of the real run (prompts that start after *RST although echo is off) now resets cleanly, with a warning in the report and
    the log; the input is flushed after the *RST settle; every raw line read is logged and a skipped prompt is marked;
  * a prompt line is never taken as a reply: '=>' is dropped, '?>' / '!>' are raised as the failure of the command they follow;
  * Echo ON: the echoed command text at *IDN? refuses the connection with a clear message; an echo line in the middle of a run is skipped and logged;
  * a reply that never comes still times out with the transport's own error; the number of lines read for one reply is bounded;
  * no write is ever repeated, and the normal (echo off, no prompts) path logs and behaves exactly as before.
The simulator's prompt / echo modes are simulation choices (drivers/simulated_8808a.py docstring), not statements about the real meter.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(ROOT / 'tests'))

from tests import live_editor_harness as H  # noqa: E402  (installs the tkinter stub)

import drivers  # noqa: E402
import fluke8808a_verification as E  # noqa: E402
from drivers.base import InstrumentError  # noqa: E402
from drivers.fluke_8808a import Fluke8808A  # noqa: E402
from drivers.simulated_8808a import make_8808a_bench  # noqa: E402
from drivers.transport import Transport, TransportError  # noqa: E402


def make(**kw):
    bench, _ct, dt = make_8808a_bench()
    for k, v in kw.items():
        setattr(dt, k, v)
    log = drivers.CommandLog()
    return dt, Fluke8808A(dt, log, label='8808A'), log


def raw(log, who='8808A'):
    """[(direction, text)] of the command log for one instrument."""
    out = []
    for line in log.lines():
        parts = line.split(None, 3)
        if parts[1] == who:
            out.append((parts[2], parts[3] if len(parts) > 3 else ''))
    return out


def written(log):
    return [t for d, t in raw(log) if d == '>>']


class ScriptTransport(Transport):
    """A transport that returns scripted lines (to test the bound and the timeout without the simulator)."""
    name = 'script'

    def __init__(self, lines, then_timeout=True):
        self.lines, self.then_timeout, self.sent, self.cleared = list(lines), then_timeout, [], 0

    def open(self): pass
    def close(self): pass

    def write(self, text):
        self.sent.append(text)

    def read(self):
        if self.lines:
            return self.lines.pop(0)
        if self.then_timeout:
            raise TransportError('read timed out')
        return '=>'

    def clear(self):
        self.cleared += 1


class RealBenchFailureTests(unittest.TestCase):
    """The log of the failing run: Echo OFF, no prompts at *IDN?, '=>' lines after *RST."""

    def run_reset(self, **kw):
        dt, d, log = make(**kw)
        with mock.patch('time.sleep'):
            d.connect()
            dt.sent.clear()
            rep = d.reset_to_defaults()
        return dt, d, log, rep

    def test_prompts_that_start_after_the_reset_no_longer_fail_the_reset(self):
        dt, d, log, rep = self.run_reset(prompts_after_reset=True, banner='FLUKE 8808A')
        self.assertTrue(rep.ok, rep.text())
        self.assertEqual(dt.sent, ['*RST', '*CLS', '*OPC?', '*ESR?', 'REMS', 'FORMAT 1', 'FORMAT?', 'TRIGGER 1', 'TRIGGER?', 'RATE S', 'RATE?', '*ESR?'])
        self.assertEqual((dt.format, dt.trigger, dt.rate), (1, 1, 'S'))

    def test_the_old_driver_failed_on_the_same_sequence(self):
        """The same bench with the driver's prompt handling switched off reproduces '*ESR? did not return a number'."""
        dt, d, log = make(prompts_after_reset=True)
        with mock.patch('time.sleep'):
            d.connect()
            with mock.patch.object(Fluke8808A, 'query', lambda self, cmd, log_as=None: drivers.Instrument.query(self, cmd, log_as)), \
                    mock.patch.object(Fluke8808A, '_discard_input', lambda self, why: None):
                rep = d.reset_to_defaults()
        self.assertFalse(rep.ok)
        self.assertIn('did not return a number', rep.text())

    def test_input_is_flushed_after_the_reset_settle_and_logged(self):
        dt, d, log, rep = self.run_reset(prompts_after_reset=True, banner='FLUKE 8808A')
        self.assertEqual(dt.cleared, 2)                                       # connect() and after the *RST settle
        lines = raw(log)
        i_rst = lines.index(('>>', '*RST'))
        self.assertEqual(lines[i_rst + 1][0], '--')
        self.assertIn('input buffer cleared after the *RST settle', lines[i_rst + 1][1])

    def test_the_flush_comes_after_the_settle(self):
        dt, d, log = make(prompts_after_reset=True)
        order = []
        with mock.patch('time.sleep', side_effect=lambda s: order.append(('sleep', s))):
            d.connect()
            order.clear()
            orig = dt.clear
            dt.clear = lambda: (order.append(('clear', None)), orig())
            d.send('reset')
        self.assertEqual(order[-2:], [('sleep', d.RESET_SETTLE_S), ('clear', None)])

    def test_the_skipped_cls_prompt_is_logged_and_marked_and_the_reply_is_the_one(self):
        dt, d, log, rep = self.run_reset(prompts_after_reset=True)
        lines = [x for x in raw(log) if x[0] != '!!']                          # the one-time warning line sits in between
        i = lines.index(('>>', '*OPC?'))
        self.assertEqual(lines[i + 1], ('<<', '=>  [prompt, skipped]'))        # the *CLS prompt
        self.assertEqual(lines[i + 2], ('<<', '1'))                            # the real *OPC? reply
        j = max(k for k, x in enumerate(lines) if x == ('>>', '*ESR?'))
        self.assertTrue(any('prompt, skipped' in t for _d, t in lines[j - 8:j + 3]))

    def test_the_report_and_the_log_carry_the_warning(self):
        dt, d, log, rep = self.run_reset(prompts_after_reset=True)
        self.assertTrue(any('prompts returned: Echo appears to be ON or was restored by *RST - turn Echo off at the front panel' in w for w in rep.warnings),
                        rep.warnings)
        self.assertIn('warning: prompts returned', rep.text())
        self.assertTrue(any(d_ == '!!' and 'prompts returned' in t for d_, t in raw(log)))

    def test_echo_off_no_prompts_is_unchanged(self):
        dt, d, log, rep = self.run_reset()
        self.assertTrue(rep.ok)
        self.assertEqual(rep.warnings, [])
        self.assertEqual((d.prompts_seen, d.echo_seen), (0, 0))
        self.assertFalse(any('[' in t for _d, t in raw(log) if _d == '<<'))
        self.assertFalse(any(d_ == '!!' for d_, _t in raw(log)))

    def test_no_write_is_repeated(self):
        dt, d, log, rep = self.run_reset(prompts_after_reset=True, banner='x')
        sent = written(log)[1:]                                   # after connect's own *IDN? / REMS / *CLS
        sent = sent[sent.index('*RST'):]
        for cmd in ('*RST', '*CLS', 'REMS', 'FORMAT 1', 'TRIGGER 1', 'RATE S'):
            self.assertEqual(sent.count(cmd), 1, cmd)


class PromptSemanticsTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch('time.sleep')
        p.start()
        self.addCleanup(p.stop)

    def test_a_stray_ready_prompt_before_a_reply_is_dropped(self):
        dt, d, log = make()
        d.connect()
        d.send('format.set', fmt=1)
        dt.out.append(('prompt', '=>'))                       # a stray prompt in front of the next reply
        self.assertEqual(d.ask('format.query').strip(), '1')
        self.assertEqual((d.prompts_seen, d.echo_seen), (1, 0))

    def test_a_command_error_prompt_after_a_set_command_is_that_commands_failure(self):
        dt, d, log = make(prompts=True)
        d.connect()
        d.write('NOTACOMMAND')                                # the meter answers it with '?>'
        with self.assertRaises(InstrumentError) as cm:
            d.ask('format.query')
        msg = str(cm.exception)
        self.assertIn("'?>'", msg)
        self.assertIn('command error', msg)
        self.assertIn("'NOTACOMMAND'", msg)
        self.assertIn('belongs to the command sent before', msg)
        self.assertTrue(any('?>  [prompt: command-error, raised as an error]' in t for _d, t in raw(log)))

    def test_an_execution_error_prompt_names_the_wire_command(self):
        dt, d, log = make(prompts=True)
        d.connect()
        d.send('wire.4')                                      # not in the ohms function: execution error
        with self.assertRaises(InstrumentError) as cm:
            d.ask('format.query')
        self.assertIn("'!>'", str(cm.exception))
        self.assertIn("'WIRE4'", str(cm.exception))
        self.assertIn('execution', str(cm.exception))

    def test_it_is_the_last_command_that_is_named_when_several_were_sent(self):
        dt, d, log = make(prompts=True)
        d.connect()
        d.send('format.set', fmt=1)
        d.write('NOTACOMMAND')
        with self.assertRaises(InstrumentError) as cm:
            d.ask('format.query')
        self.assertIn("'NOTACOMMAND'", str(cm.exception))
        self.assertIn("'FORMAT 1'", str(cm.exception))        # listed as sent since the last reply

    def test_an_error_prompt_is_never_skipped_even_when_a_reply_follows(self):
        dt, d, log = make(prompts=True)
        d.connect()
        d.write('NOTACOMMAND')
        with self.assertRaises(InstrumentError):
            d.query('FORMAT?')

    def test_the_error_is_not_retried_by_query_retry(self):
        dt, d, log = make(prompts=True)
        d.connect()
        d.write('NOTACOMMAND')
        mark = written(log).count('FORMAT?')
        with self.assertRaises(InstrumentError):
            d.query_retry('format.query', attempts=3, delay=0)
        self.assertEqual(written(log).count('FORMAT?') - mark, 1)

    def test_a_check_after_a_command_error_still_reads_esr(self):
        dt, d, log = make(prompts=True)
        d.connect()
        d.write('NOTACOMMAND')
        with self.assertRaisesRegex(InstrumentError, 'command error'):
            d.check_errors('test')                            # '?>' is raised first as the failure of NOTACOMMAND
        d.check_errors('again')

    def test_a_prompt_only_ever_ends_a_reply_after_it_is_read(self):
        dt, d, log = make(prompts=True)
        d.connect()
        self.assertEqual(d.ask('format.query').strip(), '2')     # sim power-up format; its '=>' follows and is dropped by the next query
        self.assertEqual(d.ask('trigger.query').strip(), '1')
        self.assertEqual(d.prompts_seen, d.prompts_seen)          # no error raised
        self.assertGreaterEqual(d.prompts_seen, 1)

    def test_every_raw_line_is_logged_in_order(self):
        dt, d, log = make(prompts=True)
        d.connect()
        d.ask('format.query')
        d.ask('trigger.query')
        lines = raw(log)
        i = lines.index(('>>', 'TRIGGER?'))
        self.assertEqual(lines[i:i + 3], [('>>', 'TRIGGER?'), ('<<', '=>  [prompt, skipped]'), ('<<', '1')])


class EchoTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch('time.sleep')
        p.start()
        self.addCleanup(p.stop)

    def test_echo_on_at_connect_is_refused_with_a_clear_message(self):
        dt, d, log = make(echo=True)
        with self.assertRaises(InstrumentError) as cm:
            d.connect()
        msg = str(cm.exception)
        self.assertIn("echoed the command text '*IDN?'", msg)
        self.assertIn('Echo is ON', msg)
        self.assertIn('Table 4-1, p. 4-4', msg)
        self.assertFalse(dt.opened)                          # connect() closed the port
        self.assertIn(('<<', '*IDN?  [echo of the command, refused]'), raw(log))

    def test_command_text_glued_to_the_reply_is_refused_too(self):
        dt, d, log = make()
        orig = dt.handle
        dt.handle = lambda cmd: '*IDN?FLUKE, 8808A, 1, 1.0' if cmd == '*IDN?' else orig(cmd)
        with self.assertRaisesRegex(InstrumentError, 'Echo is ON'):
            d.connect()

    def test_a_prompt_on_the_reply_line_is_still_refused(self):
        dt, d, log = make()
        orig = dt.handle
        dt.handle = lambda cmd: '=> FLUKE, 8808A, 1, 1.0' if cmd == '*IDN?' else orig(cmd)
        with self.assertRaisesRegex(InstrumentError, 'Echo is ON'):
            d.connect()

    def test_prompts_without_echo_at_connect_are_tolerated(self):
        dt, d, log = make(prompts=True)
        d.connect()
        self.assertIn('8808A', d.idn)
        self.assertEqual(d.idn.count('FLUKE'), 1)

    def test_an_echoed_line_in_the_middle_of_a_run_is_skipped_and_logged(self):
        dt, d, log = make()
        d.connect()
        dt.echo = True                                       # restored later (for example by the reset)
        self.assertEqual(d.ask('format.query').strip(), '2')
        lines = raw(log)
        i = lines.index(('>>', 'FORMAT?'))
        self.assertEqual(lines[i + 1], ('<<', 'FORMAT?  [echo of the command, skipped]'))
        self.assertEqual(d.echo_seen, 1)
        self.assertIn('echoed command line', d._prompt_warning())

    def test_echo_and_prompts_through_a_reset_still_complete_it(self):
        dt, d, log = make()
        d.connect()
        dt.echo = True
        rep = d.reset_to_defaults()
        self.assertTrue(rep.ok, rep.text())
        self.assertTrue(rep.warnings)


class TimeoutAndBoundTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch('time.sleep')
        p.start()
        self.addCleanup(p.stop)

    def make_scripted(self, lines, then_timeout=True):
        t = ScriptTransport(lines, then_timeout)
        log = drivers.CommandLog()
        return t, Fluke8808A(t, log, label='8808A'), log

    def test_a_reply_that_never_comes_times_out_with_the_transports_error(self):
        t, d, log = self.make_scripted(['=>'])
        with self.assertRaisesRegex(TransportError, 'read timed out'):
            d.query('FORMAT?')
        self.assertEqual(t.sent, ['FORMAT?'])               # one write, never repeated
        self.assertIn(('<<', '=>  [prompt, skipped]'), raw(log))

    def test_a_first_read_timeout_is_the_transports_own_error(self):
        t, d, log = self.make_scripted([])
        with self.assertRaisesRegex(TransportError, 'read timed out'):
            d.query('FORMAT?')

    def test_only_prompts_forever_stops_after_the_bound(self):
        t, d, log = self.make_scripted([], then_timeout=False)
        t.lines = ['=>'] * 50
        with self.assertRaisesRegex(InstrumentError, 'no reply to .FORMAT\\?. within 5 lines'):
            d.query('FORMAT?')
        self.assertEqual(sum(1 for d_, x in raw(log) if d_ == '<<'), d.MAX_REPLY_LINES)
        self.assertEqual(len(t.lines), 50 - d.MAX_REPLY_LINES)

    def test_the_reply_may_be_the_fifth_line(self):
        t, d, log = self.make_scripted(['=>', '=>', '=>', '=>', '2'])
        self.assertEqual(d.query('FORMAT?').strip(), '2')

    def test_an_empty_input_buffer_after_the_reset_does_not_hide_a_missing_reply(self):
        t, d, log = self.make_scripted([])
        with self.assertRaises(TransportError):
            d.ask('opc.query')
        self.assertEqual(t.sent, ['*OPC?'])


class EngineLogTests(unittest.TestCase):
    """The failed reset saves the command log while the window stays open; close() adds only what is new."""

    def setUp(self):
        self.h = H.EngineHarness().start(E)
        self.addCleanup(self.h.stop)
        p = mock.patch('time.sleep', side_effect=lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.home = tempfile.mkdtemp()
        p = mock.patch.object(Path, 'home', lambda: Path(self.home))
        p.start()
        self.addCleanup(p.stop)

    def build(self, **kw):
        E.configure()
        app = E.App(self.h.root, '8808A', demo=False)
        self.h.app = app
        app.asset.set('A-8808')
        bench, ct, dt = make_8808a_bench('5522A', True)
        for k, v in kw.items():
            setattr(dt, k, v)
        app.io = E.IO('sim', 'sim', 'Fluke 5522A', 9600, transports=(dt, ct), mods=app.pm_state)
        app.io.is_manual = app.is_manual
        return app, dt

    def shared_log(self):
        p = Path(self.home) / '.calibration_suite' / 'command_log.txt'
        return p.read_text(encoding='utf-8') if p.exists() else ''

    def test_the_engine_resets_through_the_prompts_of_the_real_bench(self):
        app, dt = self.build(prompts_after_reset=True, banner='FLUKE 8808A')
        report = app.io.reset_at_start()
        self.assertTrue(report.ok)
        self.assertTrue(any('prompts returned' in w for r in report.reports for w in r.warnings))

    def test_a_failed_reset_saves_the_log_before_the_dialog_and_close_does_not_repeat_it(self):
        app, dt = self.build()
        orig = dt.write

        def write(text):                                     # the 8808A's *CLS times out after the reset: the reset fails
            if text.strip() == '*CLS' and '*RST' in dt.sent:
                raise TransportError('simulated timeout on *CLS')
            orig(text)
        dt.write = write
        with self.assertRaises(Exception) as cm:
            app.io.reset_at_start()
        msg = str(cm.exception)
        app._reset_failed(msg)
        self.assertEqual([x for x in self.h.dialogs if x[0] == 'box' and x[1] == 'showerror'][0][2], 'Reset failed - run not started')
        text = self.shared_log()
        self.assertEqual(text.count('>>  *RST'), 2)           # the calibrator's and the 8808A's, saved now
        self.assertIn('RESET FAILED, run not started', text)
        app.io.close()                                        # the window closes later
        after = self.shared_log()
        self.assertEqual(after.count('8808A  >>  *RST'), text.count('8808A  >>  *RST'))
        self.assertEqual(after.count('RESET FAILED, run not started'), 1)

    def test_close_without_a_failed_reset_saves_the_whole_log_once(self):
        app, dt = self.build()
        app.io.reset_at_start()
        app.io.close()
        text = self.shared_log()
        self.assertEqual(text.count('--- '), 1)
        self.assertIn('Instruments reset to default settings at start', text)
        app.io.save_log()                                     # nothing new: nothing appended
        self.assertEqual(self.shared_log(), text)


if __name__ == '__main__':
    unittest.main()
