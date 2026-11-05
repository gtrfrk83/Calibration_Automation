"""R&S SMA100B driver (drivers/rs_sma100b.py) against its simulator (drivers/simulated_sma100b.py). No hardware: nothing here is evidence for the
real generator (every command stays verified=False until a bench session, NOTES.md 'Bench-first driver workflow')."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cmdreg  # noqa: E402
import driver_verify as V  # noqa: E402
import drivers  # noqa: E402
from drivers.base import InstrumentError, SafetyError  # noqa: E402
from drivers.rs_sma100b import COMMANDS, RSSMA100B  # noqa: E402
from drivers.simulated_sma100b import SimSMA100BTransport  # noqa: E402
from drivers.transport import CommandLog  # noqa: E402


def make(**kw):
    t = SimSMA100BTransport(**kw)
    return RSSMA100B(t, CommandLog()).connect(), t


def wire(t):
    return [s.upper() for s in t.sent]


class Registry(unittest.TestCase):
    def test_registry_lints_clean_and_every_command_has_a_manual_page(self):
        self.assertEqual(cmdreg.lint_registry(COMMANDS), [])
        for key, cmd in COMMANDS.items():
            self.assertRegex(cmd.ref, r'\(p\. \d', key)
            self.assertFalse(cmd.verified, f'{key}: nothing is verified before a bench session')

    def test_output_and_plumbing_are_not_overridable(self):
        for key in ('outp.on', 'outp.off', 'outp.query', 'reset', 'opc.query', 'status.clear', 'err.query', 'selftest'):
            self.assertFalse(cmdreg.is_overridable(COMMANDS[key])[0], key)

    def test_no_forbidden_command_and_no_level_limit_write(self):
        texts = ' '.join(c.template.upper() for c in COMMANDS.values())
        for bad in ('SYST:COMM', 'POW:LIM ', 'CAL', '*SAV', '*RCL', 'SYST:PROT'):
            self.assertNotIn(bad, texts)

    def test_found_by_name_and_in_the_driver_catalogue(self):
        self.assertIs(drivers.RSSMA100B, RSSMA100B)
        self.assertIn(RSSMA100B, [c for _l, c in V.driver_catalog()])


class Connect(unittest.TestCase):
    def test_connect_identifies_clears_rf_off_and_reads_fixed_state(self):
        g, t = make(level_limit=13.0, ref_source='EXT')
        self.assertIn('SMA100B', g.idn)
        self.assertEqual(wire(t)[:4], ['*IDN?', '*CLS', 'OUTP OFF', 'OUTP?'])
        self.assertEqual((g.ref_source, g.level_limit_dbm), ('EXT', 13.0))
        self.assertIn('SMAB-B106', g.options)
        self.assertTrue(g.output_off_confirmed)

    def test_wrong_model_is_refused(self):
        import drivers.simulated_sma100b as S
        old = S.IDN
        S.IDN = 'Rohde&Schwarz,SMB100A,1406.6000K02/1,3.1'
        try:
            with self.assertRaises(InstrumentError):
                RSSMA100B(SimSMA100BTransport(), CommandLog()).connect()
        finally:
            S.IDN = old

    def test_default_gpib_address_is_28_and_is_retargeted(self):
        class T(SimSMA100BTransport):
            address = ''
        t = T()
        g = RSSMA100B(t, CommandLog()).connect()
        self.assertEqual(g.address, 28)
        self.assertEqual(t.address, 'GPIB0::28::INSTR')
        t2 = T()
        RSSMA100B(t2, CommandLog(), address=5).connect()
        self.assertEqual(t2.address, 'GPIB0::5::INSTR')


class Settings(unittest.TestCase):
    def test_setup_sets_reads_back_and_leaves_rf_off(self):
        g, t = make()
        g.cw_setup()
        self.assertEqual(g.setup(2.5e9, -10.0), (2.5e9, -10.0))
        self.assertIn('FREQ 2500000000', wire(t))
        self.assertIn('POW -10.00', wire(t))
        self.assertEqual(g.read_setting(), (2.5e9, -10.0, False))

    def test_level_above_the_limit_is_refused_before_it_is_sent(self):
        g, t = make(level_limit=0.0)
        n = len(t.sent)
        with self.assertRaises(InstrumentError) as cm:
            g.set_level(5.0)
        self.assertIn('level limit', str(cm.exception))
        self.assertFalse(any(s.upper().startswith('POW ') for s in t.sent[n:]))
        self.assertEqual(g.set_level(0.0), 0.0)

    def test_out_of_range_frequency_is_an_error(self):
        g, t = make(max_hz=3e9)
        with self.assertRaises(InstrumentError) as cm:
            g.set_frequency(5e9)
        self.assertIn('-222', str(cm.exception))                             # the generator's own reason is shown ...
        self.assertEqual(t.errors, [])                                       # ... and not left for the next command
        self.assertEqual(g.set_frequency(1e9), 1e9)

    def test_offsets_left_on_the_generator_are_found(self):
        g, t = make()
        t.pow_offs = 3.0
        with self.assertRaises(InstrumentError) as cm:
            g.cw_setup()
        self.assertIn('level offset', str(cm.exception))
        t.pow_offs, t.freq_mult = 0.0, 2.0
        with self.assertRaises(InstrumentError):
            g.confirm_no_offsets()

    def test_modulation_and_sweep_are_switched_off(self):
        g, t = make()
        t.mod_on, t.freq_mode, t.pow_mode, t.unit = True, 'SWE', 'SWE', 'V'
        g.cw_setup()
        self.assertEqual((t.mod_on, t.freq_mode, t.pow_mode, t.unit), (False, 'CW', 'CW', 'DBM'))

    def test_reference_source(self):
        g, t = make()
        self.assertEqual(g.set_reference('ext'), 'EXT')
        self.assertEqual(t.ref_source, 'EXT')
        with self.assertRaises(InstrumentError):
            g.set_reference('GPS')


class Output(unittest.TestCase):
    def test_rf_on_off_confirmed(self):
        g, t = make()
        g.output(True)
        self.assertTrue(t.rf_on)
        g.output(False)
        self.assertFalse(t.rf_on)

    def test_unconfirmed_off_is_a_safety_error(self):
        g, t = make()

        class Stuck(SimSMA100BTransport):
            def _one(self, seg):
                if seg.upper() == 'OUTP?':
                    return '1'
                return super()._one(seg)
        g.t = s = Stuck()
        s.opened = True
        with self.assertRaises(SafetyError):
            g.output(False)

    def test_cleanup_switches_rf_off_and_goes_local(self):
        g, t = make()
        g.output(True)
        g.cleanup()
        self.assertFalse(t.rf_on)
        self.assertTrue(g.output_off_confirmed)
        self.assertEqual(t.local, 1)

    def test_cleanup_never_raises(self):
        g, t = make()
        t.opened = False
        g.cleanup()
        self.assertFalse(g.output_off_confirmed)


class ResetAndSelfTest(unittest.TestCase):
    def test_reset_to_defaults(self):
        g, t = make(level_limit=10.0, ref_source='EXT')
        g.output(True)
        t.mod_on = True
        rep = g.reset_to_defaults()
        self.assertTrue(rep.ok, rep.text())
        self.assertFalse(t.rf_on)
        self.assertEqual((t.ref_source, t.level_limit), ('EXT', 10.0))       # *RST leaves them alone (p. 746, 756)
        self.assertIn('EXT / 10 dBm', rep.text())

    def test_self_test(self):
        g, _t = make()
        self.assertEqual(g.self_test(), (True, '0'))
        g2, _t2 = make(selftest_code=3)
        self.assertEqual(g2.self_test(), (False, '3'))


class DriverVerify(unittest.TestCase):
    def test_every_query_answers_on_the_simulator(self):
        g, _t = make()
        plan = V.build_plan(g)
        res = V.Verifier(g, confirm=lambda st: True, simulated=True).run_plan([s for s in plan if s.sendable])
        bad = [(r.key, r.status, r.error) for r in res if r.status not in ('pass', 'check')]
        self.assertEqual(bad, [])


class BenchScript(unittest.TestCase):
    """drivers/sma100b_bench.py: the first-GPIB-session script."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, argv, answers=None):
        import contextlib
        import io
        from drivers import sma100b_bench as B
        asked = []

        def answer(prompt):
            asked.append(prompt)
            if answers is None:
                raise AssertionError(f'asked: {prompt}')
            return answers.pop(0) if answers else 'n'
        with contextlib.redirect_stdout(io.StringIO()):
            code = B.main(['--sim', '--out', self.tmp.name] + argv, answer=answer)
        record = next(Path(self.tmp.name).glob('sma100b_bench_*_SIMULATED.txt')).read_text(encoding='utf-8')
        return code, asked, record

    def test_read_only_stage_sends_no_write_and_asks_nothing(self):
        code, asked, record = self._run([])
        self.assertEqual((code, asked), (0, []))
        self.assertIn('SIMULATED - not evidence', record)
        self.assertNotIn('>>  OUTP OFF', record)
        self.assertIn('<<  Rohde&Schwarz,SMA100B', record)

    def test_declining_a_write_stops_and_rf_is_still_switched_off(self):
        code, asked, record = self._run(['--settings', '--rf'], answers=['n'])
        self.assertEqual(code, 1)
        self.assertEqual(len(asked), 1)
        self.assertIn("'*CLS'", asked[0])
        self.assertIn('STOPPED: not sent: *CLS', record)
        self.assertIn('cleanup: RF OFF confirmed', record)

    def test_yes_is_refused_on_real_hardware(self):
        from drivers import sma100b_bench as B
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            B.main(['--yes'])


if __name__ == '__main__':
    unittest.main()
