"""The driver verification engine (driver_verify.py) against the simulated bench and small fakes - no hardware, no Qt."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cmdreg  # noqa: E402
import drivers  # noqa: E402
import driver_verify as V  # noqa: E402
from drivers.simulated import make_bench  # noqa: E402
from drivers.transport import Transport, TransportError  # noqa: E402


def sim_5560a():
    bench, f, _s = make_bench()
    d = drivers.Fluke5560A(f)
    d.open(verify_model=False)
    return d


class Catalog(unittest.TestCase):
    def test_lists_the_drivers_with_commands(self):
        names = [c[0] for c in V.driver_catalog()]
        for want in ('Fluke5560A', 'TektronixTBS2000B', 'TektronixMDO3', 'TektronixTBS1000C', 'Keysight34465A'):
            self.assertTrue(any(want in n for n in names), want)
        self.assertFalse(any('Sim' in n for n in names))


class Plan(unittest.TestCase):
    def test_every_command_gets_a_step_and_a_mode(self):
        d = sim_5560a()
        plan = V.build_plan(d)
        self.assertEqual({s.key for s in plan}, set(cmdreg.merge_commands(d)))
        c = V.counts(plan)
        self.assertGreater(c['query'], 5)
        self.assertGreater(c['set'], 10)
        self.assertGreaterEqual(c['output'], 2)                       # OPER, STBY...
        self.assertTrue(all(s.default_on == (s.mode == 'query' and s.sendable) for s in plan))
        self.assertTrue(all(not s.default_on for s in plan if s.mode != 'query'))      # nothing but queries is ticked for you

    def test_calibration_commands_and_passwords_are_never_sendable(self):
        for cls in (drivers.Keithley2000Cal, drivers.Fluke8808ACal, drivers.Fluke8846A, drivers.TektronixMDO3):
            for s in V.build_plan(cls):
                if s.sendable and s.wire:
                    self.assertEqual(cmdreg._forbidden(s.wire, cls.__name__) if s.mode != 'locked' else [], [], (cls.__name__, s.key, s.wire))
                self.assertFalse(s.cmd.secret and s.sendable, (cls.__name__, s.key))


class Running(unittest.TestCase):
    def test_queries_pass_and_nothing_else_is_sent_without_confirmation(self):
        d = sim_5560a()
        plan = V.build_plan(d)
        ver = V.Verifier(d, confirm=None, simulated=True)
        res = ver.run_plan([s for s in plan if s.sendable])
        by = {r.key: r for r in res}
        self.assertTrue(all(r.status in ('pass', 'fail') for r in res if by[r.key].wire and plan_mode(plan, r.key) == 'query'))
        self.assertTrue(all(r.status == 'skipped' and r.note == 'not confirmed' for r in res if plan_mode(plan, r.key) != 'query'))
        sent = [t for t in d.log.lines() if '>>' in t]
        self.assertFalse(any(t.rstrip().endswith(('OPER', 'STBY', '*RST')) for t in sent))     # no output or reset command went out
        self.assertFalse(d.is_operating())

    def test_a_set_command_is_sent_once_read_back_and_an_output_returns_to_standby(self):
        d = sim_5560a()
        plan = {s.key: s for s in V.build_plan(d)}
        ver = V.Verifier(d, confirm=lambda st: True, simulated=True)
        r = ver.run(plan['oper.on'])
        self.assertIn(r.status, ('check', 'pass'))
        self.assertIn('standby', r.note)
        self.assertFalse(d.is_operating())
        n = sum(1 for t in d.log.lines() if t.rstrip().endswith('OPER'))
        self.assertEqual(n, 1)                                          # sent once

    def test_a_failing_write_is_not_retried(self):
        class Dead(Transport):
            def __init__(s): s.sent = []
            def open(s): pass
            def close(s): pass
            def write(s, text): s.sent.append(text); raise TransportError('timeout')
            def read(s): return ''
            def query(s, text): s.sent.append(text); return '0,"No error"' if 'ERR' in text.upper() else 'x'
        t = Dead()
        d = drivers.Fluke5560A(t)
        d.open(verify_model=False)
        plan = {s.key: s for s in V.build_plan(d)}
        r = V.Verifier(d, confirm=lambda st: True).run(plan['scope.dcv'])
        self.assertEqual(r.status, 'fail')
        self.assertEqual(sum(1 for x in t.sent if x == 'SCOPE DCV'), 1)

    def test_reply_matching(self):
        self.assertTrue(V.reply_matches('OUT 5V', '5.000000E+00 V') or V.reply_matches('OUT 5V', '5V'))
        self.assertTrue(V.reply_matches('SCOPE DCV', 'DCV'))
        self.assertFalse(V.reply_matches('STBY', '0'))


def plan_mode(plan, key):
    return next(s.mode for s in plan if s.key == key)


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'lab_registry.sqlite3'

    def run_some(self):
        d = sim_5560a()
        plan = V.build_plan(d)
        res = V.Verifier(d, confirm=lambda st: True).run_plan([s for s in plan if s.mode == 'query' and s.sendable])
        return plan, res

    def test_a_simulated_run_cannot_be_saved(self):
        plan, res = self.run_some()
        with self.assertRaises(V.SimulatedError):
            V.save_results(plan, res, driver_name='Fluke5560A', simulated=True, db=self.db)
        self.assertFalse(self.db.exists())

    def test_save_and_load_roundtrip_and_existing_schema_untouched(self):
        plan, res = self.run_some()
        rid = V.save_results(plan, res, driver_name='Fluke5560A', model='Fluke 5560A', idn='FLUKE,5560A', address='ASRL9::INSTR', tester='mike', db=self.db)
        runs = V.load_runs('Fluke5560A', db=self.db)
        self.assertEqual(runs[0][0], rid)
        self.assertEqual(runs[0][2], 'mike')
        self.assertIn(res[0].key, V.last_status('Fluke5560A', db=self.db))
        with sqlite3.connect(self.db) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables - {'sqlite_sequence'}, {'driver_verification'})        # the tool adds one table and nothing else

    def test_flags_are_compared_not_changed(self):
        plan, res = self.run_some()
        before = {s.key: s.cmd.verified for s in plan}
        notes = V.compare_flags(plan, res)
        self.assertTrue(all(n.level in ('bad', 'good', 'info') for n in notes))
        self.assertEqual(before, {s.key: s.cmd.verified for s in V.build_plan(sim_5560a())})

    def test_csv_marks_simulated_rows(self):
        plan, res = self.run_some()
        p = Path(self.tmp.name) / 'o.csv'
        V.write_csv(p, plan, res, driver_name='Fluke5560A', simulated=True)
        text = p.read_text(encoding='utf-8-sig')
        self.assertIn('SIMULATED - NOT EVIDENCE', text)
        self.assertIn('(simulated)', text)


if __name__ == '__main__':
    unittest.main()
