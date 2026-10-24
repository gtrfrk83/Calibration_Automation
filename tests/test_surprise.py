"""Stop on surprise (surprise.py): fault injection on a simulated instrument.

    python -m unittest tests.test_surprise

A scripted fake instrument speaks a tiny SCPI dialect; each test injects ONE fault (bad reply, mismatched read-back, error-queue entry, timeout, prompt
character) and checks that the guard asks once, that Stop raises SurpriseStop, that Continue goes on, that a write is never repeated and that a clean
run asks nothing.  The real-Tk dialog is checked in tests/real_tk_checks.py (check_surprise_dialog)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT)]

import cmdreg  # noqa: E402
import surprise  # noqa: E402
from cmdreg import Cmd, Placeholder  # noqa: E402
from drivers.base import Instrument, InstrumentError  # noqa: E402
from drivers.transport import CommandLog, Transport, TransportError  # noqa: E402


class FakeBus(Transport):
    """Holds one value; faults are switched on by attributes."""
    name = 'fake'

    def __init__(self):
        self.value = 0.0
        self.sent = []
        self.errors = []
        self.get_reply = None        # override for the read-back reply
        self.timeouts = 0            # next N queries time out
        self.no_apply = False        # ignore the set (read-back keeps the old value)

    def open(self): pass
    def close(self): pass

    def write(self, text):
        self.sent.append(text)
        if text.startswith('SET '):
            if not self.no_apply:
                self.value = float(text.split()[1])

    def read(self):
        raise NotImplementedError

    def query(self, text):
        self.sent.append(text)
        if self.timeouts:
            self.timeouts -= 1
            raise TransportError('timeout')
        if text == 'GET?':
            return self.get_reply if self.get_reply is not None else f'{self.value:.6g}'
        if text == 'SYST:ERR?':
            return self.errors.pop(0) if self.errors else '+0,"No error"'
        return ''


class Dev(surprise.SurpriseMixin, Instrument):
    MODEL = 'Fake'
    COMMANDS = {
        'set': Cmd('SET {value:.6g}', 'Set', placeholders={'value': Placeholder('float', '.6g', 1.0)}, kind='set', readback='get'),
        'get': Cmd('GET?', 'Get', kind='query'),
        'err.query': Cmd('SYST:ERR?', 'Errors', kind='query', risk='locked'),
    }


def make(virtual=False, answers=None):
    bus = FakeBus()
    log = CommandLog()
    log.virtual = virtual
    dev = Dev(bus, log, 'FAKE')
    seen = []
    ans = list(answers or [])

    def handler(s):
        seen.append(s)
        return ans.pop(0) if ans else False

    return dev, bus, seen, handler


class Surprises(unittest.TestCase):
    def test_clean_run_never_asks(self):
        dev, bus, seen, handler = make()
        dev.enable_surprise(handler)
        for v in (1.0, 2.5, 0.0):
            dev.set_checked('set', v)
        self.assertEqual(seen, [])
        self.assertEqual(float(dev.ask_checked('get')), 0.0)
        self.assertEqual([l for l in dev.log.lines() if ' !!  ' in l], [])

    def test_mismatched_readback_stop_and_no_retry(self):
        dev, bus, seen, handler = make(answers=[False])
        dev.enable_surprise(handler)
        bus.no_apply = True
        with self.assertRaises(surprise.SurpriseStop) as cm:
            dev.set_checked('set', 3.0)
        self.assertEqual(len(seen), 1)
        s = seen[0]
        self.assertEqual((s.kind, s.command, s.reply, s.expected), ('readback', 'SET 3', '0', '3.0'))
        self.assertEqual(sum(1 for t in bus.sent if t.startswith('SET ')), 1, 'the write is never repeated')
        self.assertIsInstance(cm.exception, InstrumentError)
        self.assertTrue(any('SURPRISE readback' in l for l in dev.log.lines()))
        self.assertTrue(any('operator chose Stop' in l for l in dev.log.lines()))

    def test_mismatched_readback_continue(self):
        dev, bus, seen, handler = make(answers=[True])
        dev.enable_surprise(handler)
        bus.no_apply = True
        dev.set_checked('set', 3.0)                       # does not raise
        self.assertEqual(len(seen), 1)
        self.assertEqual(sum(1 for t in bus.sent if t.startswith('SET ')), 1)
        self.assertTrue(any('operator chose Continue' in l for l in dev.log.lines()))

    def test_bad_reply_formats(self):
        for reply, why in (('', 'empty'), ('=>', 'prompt'), ('?>', 'prompt'), ('abc', 'not a number')):
            dev, bus, seen, handler = make(answers=[False])
            dev.enable_surprise(handler)
            bus.get_reply = reply
            with self.assertRaises(surprise.SurpriseStop):
                dev.set_checked('set', 1.0)
            self.assertEqual(len(seen), 1, reply)
            self.assertEqual(seen[0].kind, 'reply')
            self.assertIn(why, seen[0].expected, reply)
            self.assertEqual(sum(1 for t in bus.sent if t.startswith('SET ')), 1)

    def test_error_queue_after_write(self):
        dev, bus, seen, handler = make(answers=[False])
        dev.enable_surprise(handler)
        bus.errors = ['-222,"Data out of range"']
        with self.assertRaises(surprise.SurpriseStop):
            dev.set_checked('set', 1.0)
        self.assertEqual([s.kind for s in seen], ['errqueue'])
        self.assertIn('-222', seen[0].reply)
        self.assertEqual(sum(1 for t in bus.sent if t.startswith('SET ')), 1)

    def test_error_queue_continue(self):
        dev, bus, seen, handler = make(answers=[True])
        dev.enable_surprise(handler)
        bus.errors = ['-222,"Data out of range"']
        dev.set_checked('set', 1.0)
        self.assertEqual(len(seen), 1)

    def test_timeout_read_only_retried_once_then_surprise(self):
        dev, bus, seen, handler = make(answers=[False])
        dev.enable_surprise(handler)
        bus.timeouts = 1                                   # one timeout: the retry succeeds, no dialog
        self.assertEqual(float(dev.ask_checked('get')), 0.0)
        self.assertEqual(seen, [])
        self.assertEqual(bus.sent.count('GET?'), 2)
        bus.sent.clear()
        bus.timeouts = 5                                   # keeps timing out: ONE retry, then a surprise
        with self.assertRaises(surprise.SurpriseStop):
            dev.ask_checked('get')
        self.assertEqual(bus.sent.count('GET?'), 2)
        self.assertEqual(seen[-1].kind, 'reply')

    def test_write_timeout_is_not_retried(self):
        dev, bus, seen, handler = make()
        dev.enable_surprise(handler)
        bus.timeouts = 1                                   # the read-back query times out, the write already went out once
        dev.set_checked('set', 2.0)
        self.assertEqual(sum(1 for t in bus.sent if t.startswith('SET ')), 1)

    def test_no_handler_means_stop(self):
        dev, bus, seen, handler = make()
        dev.enable_surprise(None)
        bus.get_reply = ''
        with self.assertRaises(surprise.SurpriseStop):
            dev.set_checked('set', 1.0)

    def test_handler_exception_means_stop(self):
        dev, bus, seen, _ = make()
        dev.enable_surprise(lambda s: 1 / 0)
        bus.get_reply = ''
        with self.assertRaises(surprise.SurpriseStop):
            dev.set_checked('set', 1.0)

    def test_guard_off_behaves_like_a_plain_driver(self):
        dev, bus, seen, handler = make()
        bus.no_apply = True
        with self.assertRaises(InstrumentError) as cm:
            dev.set_checked('set', 3.0)
        self.assertNotIsInstance(cm.exception, surprise.SurpriseStop)
        dev2, bus2, *_ = make()
        bus2.errors = ['-100,"Command error"']
        with self.assertRaises(InstrumentError):
            dev2.set_checked('set', 1.0)

    def test_demo_log_is_unaffected(self):
        dev, bus, seen, handler = make(virtual=True, answers=[True])
        g = dev.enable_surprise(handler)
        self.assertFalse(g.enabled)
        bus.no_apply = True
        with self.assertRaises(InstrumentError):           # plain driver behaviour, no dialog
            dev.set_checked('set', 3.0)
        self.assertEqual(seen, [])
        forced, bus3, seen3, h3 = make(virtual=True, answers=[True])
        forced.enable_surprise(h3, force=True)
        bus3.no_apply = True
        forced.set_checked('set', 3.0)
        self.assertEqual(len(seen3), 1)

    def test_set_without_readback_declared_is_refused(self):
        class NoRb(Dev):
            COMMANDS = {'raw': Cmd('RAW {value:.6g}', 'raw', placeholders={'value': Placeholder('float', '.6g', 1.0)}, kind='set')}
        dev = NoRb(FakeBus(), CommandLog(), 'X')
        with self.assertRaises(InstrumentError):
            dev.set_checked('raw', 1.0)
        self.assertEqual(dev.t.sent, [], 'nothing was written')

    def test_text_readback(self):
        class Txt(Dev):
            COMMANDS = {'err.query': Cmd('SYST:ERR?', 'Errors', kind='query', risk='locked'),
                        'mode': Cmd('MODE {m}', 'mode', placeholders={'m': Placeholder('enum', '', 'DC', enum=('DC', 'AC'))}, kind='set', readback='mode?'),
                        'mode?': Cmd('MODE?', 'mode?', kind='query')}
        bus = FakeBus()
        bus.get_reply = None
        bus.query = lambda t: (bus.sent.append(t) or ('+0,"No error"' if t == 'SYST:ERR?' else 'AC'))
        dev = Txt(bus, CommandLog(), 'T')
        seen = []
        dev.enable_surprise(lambda s: seen.append(s) or False)
        dev.set_checked('mode', 'AC', name='m')
        self.assertEqual(seen, [])
        with self.assertRaises(surprise.SurpriseStop):
            dev.set_checked('mode', 'DC', name='m')

    def test_log_tail_and_masking(self):
        dev, bus, seen, handler = make(answers=[False])
        dev.enable_surprise(handler)
        for i in range(30):
            dev.log.add('>>', f'filler {i}', 'FAKE')
        bus.get_reply = ''
        with self.assertRaises(surprise.SurpriseStop):
            dev.set_checked('set', 1.0)
        self.assertLessEqual(len(seen[0].log_tail), surprise.LOG_TAIL)
        self.assertTrue(any('SET 1' in l for l in seen[0].log_tail))

    def test_secret_command_is_masked_in_the_dialog_text(self):
        class Sec(Dev):
            COMMANDS = {'pw': Cmd('PASSWORD {pw}', 'pw', placeholders={'pw': Placeholder('secret')}, kind='set', readback='get'),
                        'get': Cmd('GET?', 'Get', kind='query')}
        bus = FakeBus()
        bus.get_reply = ''
        dev = Sec(bus, CommandLog(), 'S')
        seen = []
        dev.enable_surprise(lambda s: seen.append(s) or False)
        with self.assertRaises(surprise.SurpriseStop):
            dev.set_checked('pw', 'hunter2', name='pw', check_errors=False)
        text = ' '.join(seen[0].lines() + seen[0].log_tail)
        self.assertNotIn('hunter2', text)

    def test_attach_guard_on_an_existing_style_driver(self):
        bus = FakeBus()
        log = CommandLog()
        plain = type('Plain', (Instrument,), {'MODEL': 'P', 'COMMANDS': Dev.COMMANDS})(bus, log, 'P')
        seen = []
        self.assertIsNotNone(surprise.attach_guard(plain, lambda s: seen.append(s) or False))
        self.assertEqual(plain.ask('get'), '0')
        bus.get_reply = '=>'
        with self.assertRaises(surprise.SurpriseStop):
            plain.ask('get')
        self.assertEqual(len(seen), 1)
        virt = CommandLog()
        virt.virtual = True
        p2 = type('Plain2', (Instrument,), {'MODEL': 'P', 'COMMANDS': Dev.COMMANDS})(FakeBus(), virt, 'P')
        self.assertIsNone(surprise.attach_guard(p2, lambda s: True))

    def test_stop_only_never_continues_even_if_the_handler_says_yes(self):
        dev, bus, seen, handler = make(answers=[True])
        g = surprise.Guard(dev, handler)
        with self.assertRaises(surprise.SurpriseStop):
            g.surprise('errqueue', 'OUT 1', '-222', 'empty', stop_only=True)
        self.assertTrue(seen[0].stop_only)
        self.assertTrue(any('Continue is not offered' in l for l in dev.log.lines()))
        self.assertFalse(any('operator chose Continue' in l for l in dev.log.lines()))

    def test_attach_guard_expect_stop_only_and_timeout_retry(self):
        bus = FakeBus()
        plain = type('Plain', (Instrument,), {'MODEL': 'P', 'COMMANDS': Dev.COMMANDS})(bus, CommandLog(), 'P')
        seen = []
        surprise.attach_guard(plain, lambda s: seen.append(s) or True, expect={'get': 'float'}, stop_only=True)
        self.assertEqual(plain.ask('get'), '0')
        bus.get_reply = 'abc'
        with self.assertRaises(surprise.SurpriseStop):                      # the handler said Continue; stop_only wins
            plain.ask('get')
        self.assertTrue(seen[-1].stop_only)
        self.assertIn('not a number', seen[-1].expected)
        bus.get_reply = None
        bus.timeouts = 1                                                    # one timeout: retried once, no surprise
        n = len(seen)
        self.assertEqual(plain.ask('get'), '0')
        self.assertEqual(len(seen), n)
        self.assertEqual(bus.sent.count('GET?'), 2 + 2)                     # 1 ok + 1 bad + (timed out + retry)
        bus.timeouts = 2                                                    # timeout twice: a surprise with an empty reply, stop only
        with self.assertRaises(surprise.SurpriseStop):
            plain.ask('get')
        self.assertEqual(seen[-1].reply, '')

    def test_attach_guard_stop_only_for_chosen_keys(self):
        bus = FakeBus()
        plain = type('Plain', (Instrument,), {'MODEL': 'P', 'COMMANDS': Dev.COMMANDS})(bus, CommandLog(), 'P')
        seen = []
        surprise.attach_guard(plain, lambda s: seen.append(s) or True, stop_only={'get'})
        bus.errors = ['']
        self.assertEqual(plain.ask('err.query'), '')                         # Continue offered for this key, handler said yes
        self.assertFalse(seen[-1].stop_only)

    def test_checked_routes_the_drivers_own_exception(self):
        bus = FakeBus()
        dev = type('Plain', (Instrument,), {'MODEL': 'P', 'COMMANDS': Dev.COMMANDS})(bus, CommandLog(), 'P')

        def drv_check(ctx=''):
            r = dev.ask('err.query').strip()
            if r.split(',')[0] not in ('0', '+0'):
                raise InstrumentError(f'rejected {ctx}: {r}')

        calls = []
        self.assertIsNone(surprise.checked(dev, drv_check, 'x'))              # no guard: plain call, plain exception
        bus.errors = ['-113,"Undefined header"']
        with self.assertRaises(InstrumentError) as cm:
            surprise.checked(dev, drv_check, 'x')
        self.assertNotIsInstance(cm.exception, surprise.SurpriseStop)
        surprise.attach_guard(dev, lambda s: calls.append(s) or True)
        bus.errors = ['-113,"Undefined header"']
        self.assertIsNone(surprise.checked(dev, drv_check, 'y'))              # Continue
        self.assertEqual((calls[0].kind, calls[0].reply, calls[0].command), ('errqueue', '-113,"Undefined header"', 'SYST:ERR?'))
        bus.errors = ['-113,"Undefined header"']
        with self.assertRaises(surprise.SurpriseStop):
            surprise.checked(dev, drv_check, 'z', stop_only=True)
        self.assertTrue(calls[-1].stop_only)
        self.assertEqual(bus.sent.count('SYST:ERR?'), 1 + 1 + 1 + 1, 'one query per check, never repeated')

    def test_last_exchange_shows_the_entries_of_a_drained_queue(self):
        dev, bus, seen, handler = make()
        for r in ('-113,"Undefined header"', '-221,"Settings conflict"', '+0,"No error"'):
            dev.log.add('>>', 'SYST:ERR?', dev.label)
            dev.log.add('<<', r, dev.label)
        self.assertEqual(surprise._last_exchange(dev), ('SYST:ERR?', '-113,"Undefined header" | -221,"Settings conflict"'))
        dev.log.add('>>', 'READ?', dev.label)
        dev.log.add('<<', '1.5', dev.label)
        self.assertEqual(surprise._last_exchange(dev), ('READ?', '1.5'))
        dev.log.add('>>', 'OUT 1V', dev.label)                 # a write with no reply: the command is the write, no reply
        self.assertEqual(surprise._last_exchange(dev), ('OUT 1V', ''))

    def test_checked_lets_safety_errors_through(self):
        from drivers.base import SafetyError
        dev, bus, seen, handler = make(answers=[True])
        surprise.attach_guard(dev, handler)

        def unsafe():
            raise SafetyError('standby not confirmed')
        with self.assertRaises(SafetyError):
            surprise.checked(dev, unsafe)
        self.assertEqual(seen, [])

    def test_check_reply(self):
        c = surprise.check_reply
        self.assertIsNone(c('1.5E-3', 'float'))
        self.assertIsNone(c('+1.5', 'float'))
        self.assertIsNone(c('3', 'int'))
        self.assertIsNotNone(c('3.5', 'int'))
        self.assertIsNone(c('OK', r'OK$'))
        self.assertIsNotNone(c('NO', r'OK$'))
        self.assertIsNotNone(c('  ', 'any'))
        self.assertTrue(surprise.error_queue_clean('+0,"No error"'))
        self.assertTrue(surprise.error_queue_clean('0, No error'))
        self.assertFalse(surprise.error_queue_clean('-113,"Undefined header"'))

    def test_tk_handler_never_hangs_when_nothing_services_the_queue(self):
        """A worker thread asks; no poller runs on the Tk thread (fake root whose after() does nothing): the answer is Stop within START_WAIT."""
        import threading
        from unittest import mock

        class Root:
            def after(self, ms, fn):
                return 'x'
        with mock.patch.object(surprise._TkAsker, 'START_WAIT', 0.2):
            handler = surprise.tk_handler(Root())
            out = []
            t = threading.Thread(target=lambda: out.append(handler(surprise.Surprise('reply', 'X', 'GET?', '', 'a value'))))
            t.start()
            t.join(5)
        self.assertEqual(out, [False])

    def test_tk_handler_worker_is_served_by_the_poller(self):
        """The poller (what root.after drives on the Tk thread) picks the worker's request up and the answer comes back; Tk is never called by the worker."""
        import threading
        from unittest import mock

        class Root:
            def after(self, ms, fn):
                return 'x'
        shown = []
        with mock.patch.object(surprise, '_dialog', lambda root, title, s: shown.append(s) or True):
            asker = surprise._TkAsker(Root(), 't')
            out = []
            t = threading.Thread(target=lambda: out.append(asker.ask(surprise.Surprise('reply', 'X', 'GET?', '', 'a value'))))
            t.start()
            for _ in range(100):
                asker._tick()                                  # what the Tk thread does every POLL_MS
                if not t.is_alive():
                    break
                t.join(0.02)
            t.join(5)
        self.assertEqual(out, [True])
        self.assertEqual(len(shown), 1)


class TemplateIsWired(unittest.TestCase):
    def test_template_uses_the_mixin(self):
        import drivers._template as tpl
        self.assertTrue(issubclass(tpl.ModelName, surprise.SurpriseMixin))

    def test_shared_files_do_not_import_surprise(self):
        for rel in ('drivers/base.py', 'drivers/transport.py', 'handheld_dmm.py', 'fgen_verification.py', 'tds2000c_verification.py'):     # not wired yet (the wired engines import it: tests/test_surprise_wiring.py)
            self.assertNotIn('import surprise', (ROOT / rel).read_text(encoding='utf-8'), rel)


def _tk_python():
    """A Python that has tkinter: this one, else the uv-managed ones (CI-less sandbox)."""
    import glob
    import subprocess
    cands = [sys.executable] + sorted(glob.glob(str(Path.home() / '.local/share/uv/python/*/bin/python3')))
    for c in cands:
        try:
            if subprocess.run([c, '-c', 'import tkinter'], capture_output=True, timeout=60).returncode == 0:
                return c
        except (OSError, subprocess.SubprocessError):
            pass
    return None


class RealTkDialog(unittest.TestCase):
    def test_dialog_on_a_real_tk(self):
        import os
        import shutil
        import subprocess
        py = _tk_python()
        if py is None:
            self.skipTest('no Python with tkinter')
        cmd = [py, str(ROOT / 'tests' / 'real_tk_surprise.py')]
        if not os.environ.get('DISPLAY'):
            xvfb = shutil.which('xvfb-run')
            if not xvfb:
                self.skipTest('no display and no xvfb-run')
            cmd = [xvfb, '-a', '-s', '-screen 0 1280x800x24'] + cmd
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + '\n' + r.stderr[-3000:])
        self.assertIn('ALL OK', r.stdout)


if __name__ == '__main__':
    unittest.main()
