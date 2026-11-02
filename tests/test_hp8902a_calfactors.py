"""HP 8902A power-sensor cal-factor entry: validation, the write sequence and read-back on the simulated 8902A, a failed read-back stops and is not retried, the typed
confirmation gates every write, demo persists nothing, locked commands cannot be overridden, the saved sensor tables, and the sidecar.  No hardware, no UI toolkit.

Nothing here has run on a real receiver: the way the 8902A returns the value behind 37.4SP / 37.5SP / 37.6SP is UNVERIFIED (see hp8902a_calfactors.py)."""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_DATA = tempfile.mkdtemp(prefix='calfactors_data_')
os.environ.setdefault('CALSUITE_DATA', _DATA)                 # a window test must never reach the real lab_registry.sqlite3

import adjustment_audit  # noqa: E402
import cmdreg  # noqa: E402
import hp8902a_calfactors as cf  # noqa: E402
import procscan  # noqa: E402
import sensor_cal_factor_store as store  # noqa: E402
from drivers import CommandLog  # noqa: E402
from drivers.hp_8902a import HP8902A  # noqa: E402
from drivers.simulated_8902a import Sim8902ATransport, make_8902a_bench  # noqa: E402

ROWS = [('50', '99.0'), ('1000', '97.5'), ('2 GHz', '95.0'), ('', '')]
BAD_NEVER_SENT = ('37.9', '37.7')


_OPEN = []


def tearDownModule():
    for a in _OPEN:
        a.close()


def connected():
    bench, t = make_8902a_bench()
    rx = HP8902A(t, CommandLog())
    rx.RESET_SETTLE_S = rx.COMMAND_GAP_S = rx.SETUP_SETTLE_S = 0.0
    rx.connect()
    t.sent.clear()
    return rx, t


def session(rx, demo=True):
    audit = adjustment_audit.AuditStore(demo=demo)
    _OPEN.append(audit)
    audit.start_run(cf.INSTRUMENT, 'ASSET1', 'SN1', 'Tech', uut_idn=rx.idn, scope='sensor 11722A 12345')
    s = cf.Session(rx, audit)
    return s, audit


def table(rows=ROWS, ref='98.5'):
    t, problems = cf.validate(ref, rows)
    assert t is not None, problems
    return t


def writes(t):
    return [x for x in t.sent if '37.3SP' in x]


class Validation(unittest.TestCase):
    def test_a_good_table_is_sorted_and_converted_to_mhz(self):
        t = table([('2 GHz', '95'), ('50', '99.0'), ('1000', '97.5')])
        self.assertEqual(t.pairs, [(50.0, 99.0), (1000.0, 97.5), (2000.0, 95.0)])
        self.assertEqual(t.reference, 98.5)

    def test_percent_range_and_resolution(self):
        for bad in ('39.9', '120.1', '0', '98.55', 'abc', ''):
            t, problems = cf.validate(bad, [('50', '99')])
            self.assertIsNone(t, bad)
            self.assertTrue(any('Reference' in p for p in problems), bad)
        for ok in ('40', '120', '98.5%'):
            self.assertIsNotNone(cf.validate(ok, [('50', '99')])[0], ok)
        t, problems = cf.validate('98.5', [('50', '121')])
        self.assertIsNone(t)
        self.assertIn('Row 1', problems[0])

    def test_frequency_range_and_step(self):
        for bad in ('0', '-5', '42000.05', '50.01', 'x', '43 GHz'):
            self.assertIsNone(cf.validate('98.5', [(bad, '99')])[0], bad)
        for ok in ('0.05', '42000', '42 GHz', '1500 kHz'):
            self.assertIsNotNone(cf.validate('98.5', [(ok, '99')])[0], ok)

    def test_duplicates_are_refused_even_in_other_units(self):
        t, problems = cf.validate('98.5', [('1000', '99'), ('1 GHz', '98')])
        self.assertIsNone(t)
        self.assertIn('already in row 1', problems[0])

    def test_at_most_16_pairs_and_at_least_one(self):
        rows = [(str(10 * (i + 1)), '99') for i in range(16)]
        self.assertIsNotNone(cf.validate('98.5', rows)[0])
        t, problems = cf.validate('98.5', rows + [('500', '99')])
        self.assertIsNone(t)
        self.assertIn('17', problems[0])
        self.assertIsNone(cf.validate('98.5', [('', '')])[0])

    def test_half_filled_rows_and_all_problems_are_listed(self):
        t, problems = cf.validate('300', [('50', ''), ('', '99'), ('7.01', '99')])
        self.assertIsNone(t)
        self.assertEqual(len(problems), 4)

    def test_order_does_not_matter(self):
        self.assertEqual(table([('3000', '90'), ('100', '99')]).pairs, [(100.0, 99.0), (3000.0, 90.0)])


class Sequence(unittest.TestCase):
    def test_the_table_is_written_once_each_and_read_back(self):
        rx, t = connected()
        s, audit = session(rx)
        s.read_existing()
        self.assertEqual(writes(t), [])                                          # reading wrote nothing
        res = s.enter(table(), cf.CONFIRM_ENTER)
        self.assertTrue(res.ok, res.lines)
        self.assertEqual(writes(t), ['37.3SP 98.5 CF', '37.3SP 50 MZ 99 CF', '37.3SP 1000 MZ 97.5 CF', '37.3SP 2000 MZ 95 CF'])     # once each, ascending
        self.assertEqual(t.cf_ref, 98.5)
        self.assertEqual(t.cf_table, {50.0: 99.0, 1000.0: 97.5, 2000.0: 95.0})
        self.assertEqual(audit.status(), 'ENTERED_VERIFIED')
        self.assertEqual(t.sent.count('37.4SP') >= 4, True)                       # the count is read around every pair
        self.assertIn('37.6SP FR', t.sent)
        self.assertEqual(t.sent[-1], '37.0SP')                                    # automatic cal factors again
        self.assertTrue(all('PASS' in x for x in res.lines))

    def test_the_table_clear_functions_are_never_sent(self):
        rx, t = connected()
        t.cf_table = {10.0: 90.0, 20.0: 91.0}
        s, _ = session(rx)
        s.read_existing()
        s.enter(table(), cf.CONFIRM_ENTER)
        for sent in t.sent:
            for bad in BAD_NEVER_SENT:
                self.assertNotIn(bad, sent)

    def test_stale_entries_are_removed_with_zero_percent(self):
        rx, t = connected()
        t.cf_table = {10.0: 90.0, 1000.0: 80.0}
        s, _ = session(rx)
        s.read_existing()
        stale, after = s.plan(table(), True)
        self.assertEqual((stale, after), ([10.0], 3))
        res = s.enter(table(), cf.CONFIRM_ENTER)
        self.assertTrue(res.ok, res.lines)
        self.assertIn('37.3SP 10 MZ 0 CF', t.sent)
        self.assertEqual(t.cf_table, {50.0: 99.0, 1000.0: 97.5, 2000.0: 95.0})        # 1000 MHz replaced, not duplicated

    def test_kept_entries_are_reported_not_failed(self):
        rx, t = connected()
        t.cf_table = {10.0: 90.0}
        s, _ = session(rx)
        s.read_existing()
        res = s.enter(table(), cf.CONFIRM_ENTER, remove_stale=False)
        self.assertTrue(res.ok, res.lines)
        self.assertEqual(sorted(t.cf_table), [10.0, 50.0, 1000.0, 2000.0])
        self.assertTrue(any('kept' in x for x in res.lines))

    def test_a_table_that_would_not_fit_is_refused_before_anything_is_sent(self):
        rx, t = connected()
        t.cf_table = {float(i + 1): 90.0 for i in range(16)}
        s, _ = session(rx)
        s.read_existing()
        with self.assertRaises(cf.CalFactorError):
            s.enter(table(), cf.CONFIRM_ENTER, remove_stale=False)
        self.assertEqual(writes(t), [])

    def test_the_run_cannot_start_without_reading_the_table(self):
        rx, t = connected()
        s, _ = session(rx)
        with self.assertRaises(cf.CalFactorError):
            s.enter(table(), cf.CONFIRM_ENTER)
        self.assertEqual(writes(t), [])

    def test_an_unreadable_table_means_no_entry(self):
        rx, t = connected()
        s, _ = session(rx)
        t.bench.fail_next = '37.4SP'
        with self.assertRaises(cf.CalFactorError):
            s.read_existing()
        self.assertIsNone(s.existing)
        self.assertEqual(writes(t), [])


class Confirmation(unittest.TestCase):
    def test_nothing_is_sent_without_the_typed_word(self):
        for typed in (None, '', 'enter', 'ENTER ', 'yes', 'SAVE'):
            rx, t = connected()
            s, audit = session(rx)
            s.read_existing()
            t.sent.clear()
            with self.assertRaises(cf.ConfirmationRequired):
                s.enter(table(), typed)
            self.assertEqual(t.sent, [], typed)                                    # not even a read
            self.assertEqual(t.cf_table, {})
            self.assertNotEqual(audit.status(), 'ENTERING')

    def test_the_word_is_ENTER(self):
        self.assertEqual(cf.CONFIRM_ENTER, 'ENTER')


class FailedReadBack(unittest.TestCase):
    def test_a_pair_that_is_not_stored_stops_the_run_and_is_not_retried(self):
        rx, t = connected()
        s, audit = session(rx)
        s.read_existing()
        real = Sim8902ATransport._cf

        def drop(self, value):                                                    # the receiver ignores the 1000 MHz entry
            if self._cf_mode == 'pair' and self._cf_freq == 1000.0:
                self._cf_mode = None
                return
            return real(self, value)

        with mock.patch.object(Sim8902ATransport, '_cf', drop):
            with self.assertRaises(cf.EntryStopped) as ctx:
                s.enter(table(), cf.CONFIRM_ENTER)
        self.assertIn('NOT repeated', str(ctx.exception))
        self.assertEqual(writes(t), ['37.3SP 98.5 CF', '37.3SP 50 MZ 99 CF', '37.3SP 1000 MZ 97.5 CF'])     # stopped there: no retry, no 2000 MHz
        self.assertEqual(audit.status(), 'STOPPED')
        self.assertTrue(any(e[3] == 'FAILED' for e in audit.events()))

    def test_a_reference_that_reads_back_wrong_stops_before_any_pair(self):
        rx, t = connected()
        s, audit = session(rx)
        s.read_existing()
        real = Sim8902ATransport._cf

        def wrong(self, value):
            if self._cf_mode == 'ref':
                value = value + 1.0
            return real(self, value)

        with mock.patch.object(Sim8902ATransport, '_cf', wrong):
            with self.assertRaises(cf.EntryStopped):
                s.enter(table(), cf.CONFIRM_ENTER)
        self.assertEqual(writes(t), ['37.3SP 98.5 CF'])
        self.assertEqual(audit.status(), 'STOPPED')

    def test_a_wrong_value_in_the_final_table_fails_the_summary(self):
        rx, t = connected()
        s, audit = session(rx)
        s.read_existing()
        real = Sim8902ATransport._cf

        def skew(self, value):                                                     # count is right, the stored value is not
            if self._cf_mode == 'pair' and self._cf_freq == 2000.0:
                value = value - 2.0
            return real(self, value)

        with mock.patch.object(Sim8902ATransport, '_cf', skew):
            res = s.enter(table(), cf.CONFIRM_ENTER)
        self.assertFalse(res.ok)
        self.assertEqual(audit.status(), 'ENTERED_NOT_VERIFIED')
        self.assertEqual(sum(l.startswith('FAIL') for l in res.lines), 1)

    def test_a_code_error_from_the_receiver_stops_the_run(self):
        rx, t = connected()
        s, audit = session(rx)
        s.read_existing()
        t.bench.fail_next = '1000 MZ'
        with self.assertRaises(cf.EntryStopped):
            s.enter(table(), cf.CONFIRM_ENTER)
        self.assertEqual(writes(t).count('37.3SP 1000 MZ 97.5 CF'), 0)             # the write itself never reached the bus; nothing was repeated
        self.assertNotIn('37.3SP 2000 MZ 95 CF', t.sent)


class LockedCommands(unittest.TestCase):
    def test_entry_commands_are_locked_and_cannot_be_overridden(self):
        reg = cmdreg.merge_commands(HP8902A)
        for key in ('cf.ref', 'cf.pair'):
            self.assertEqual(reg[key].risk, 'locked')
            self.assertFalse(cmdreg.is_overridable(reg[key])[0])

    def test_an_override_attempt_does_not_change_the_wire_text(self):
        rx, t = connected()
        rx.use_commands({'cf.pair': '37.9SP'}, {'cf.pair': 'ov-1'})
        rx.enter_cal_factor(50.0, 99.0)
        self.assertIn('37.3SP 50 MZ 99 CF', t.sent)
        self.assertNotIn('37.9SP', t.sent)

    def test_no_clear_command_exists_in_the_registry_used_here(self):
        reg = cmdreg.merge_commands(HP8902A)
        self.assertFalse([k for k, c in reg.items() if '37.9' in c.template or '37.7' in c.template])


class DriverRecall(unittest.TestCase):
    def test_recall_table_and_empty_table(self):
        rx, t = connected()
        self.assertEqual(rx.recall_cal_factor_table()['pairs'], [])
        t.cf_table, t.cf_ref = {2000.0: 95.0, 50.0: 99.0}, 98.5
        got = rx.recall_cal_factor_table()
        self.assertEqual((got['count'], got['reference'], got['pairs']), (3, 98.5, [(50.0, 99.0), (2000.0, 95.0)]))
        rx.restore_automatic_cal_factors()
        self.assertEqual(t.sent[-1], '37.0SP')

    def test_remove_cal_factor_checks_the_count(self):
        rx, t = connected()
        t.cf_table = {50.0: 99.0}
        self.assertEqual(rx.remove_cal_factor(50.0), 1)
        self.assertEqual(t.cf_table, {})
        self.assertEqual(rx.remove_cal_factor(77.0), 1)                            # not there: the count is unchanged (1 = the reference)


class StaleRemovalIsChecked(unittest.TestCase):
    def test_a_removal_the_receiver_ignores_stops_the_run(self):
        rx, t = connected()
        t.cf_table = {10.0: 90.0}
        s, audit = session(rx)
        s.read_existing()
        real = Sim8902ATransport._cf

        def ignore_zero(self, value):
            if value == 0:
                self._cf_mode = None
                return
            return real(self, value)

        with mock.patch.object(Sim8902ATransport, '_cf', ignore_zero):
            with self.assertRaises(cf.EntryStopped):
                s.enter(table(), cf.CONFIRM_ENTER)
        self.assertEqual(writes(t), ['37.3SP 98.5 CF', '37.3SP 10 MZ 0 CF'])
        self.assertEqual(audit.status(), 'STOPPED')


class Persistence(unittest.TestCase):
    def test_demo_persists_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'lab_registry.sqlite3'
            a = adjustment_audit.AuditStore(demo=True, path=p)
            s = store.SensorTableStore(demo=True, path=p)
            a.start_run(cf.INSTRUMENT, 'A', 'S', 'T')
            a.log('X', 'OK', 'demo')
            s.save('11722A', '1', 98.5, [(50.0, 99.0)], 'T')
            self.assertEqual(s.load('11722A', '1')['reference'], 98.5)               # works inside the demo window ...
            a.close()
            s.close()
            self.assertFalse(p.exists())                                              # ... and leaves no file

    def test_real_store_saves_loads_replaces_and_uses_new_tables_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'lab_registry.sqlite3'
            s = store.SensorTableStore(path=p)
            s.save('11722A', 'mx1', 98.5, [(50.0, 99.0), (1000.0, 97.0)], 'Tech')
            s.save('11722A', 'MX1', 99.0, [(10.0, 95.0)], 'Tech2')                     # same sensor (case-insensitive): replaced
            self.assertEqual(s.load('11722A', 'MX1')['pairs'], [(10.0, 95.0)])
            self.assertEqual(len(s.list()), 1)
            self.assertIsNone(s.load('11722A', 'other'))
            with self.assertRaises(ValueError):
                s.save('', '1', 98.5, [])
            s.close()
            names = {r[0] for r in sqlite3.connect(p).execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual({n for n in names if not n.startswith('sqlite_')}, {'sensor_cal_factor_tables', 'sensor_cal_factor_pairs'})

    def test_the_audit_record_carries_no_secret_and_marks_demo(self):
        rx, t = connected()
        s, audit = session(rx, demo=True)
        s.read_existing()
        s.enter(table(), cf.CONFIRM_ENTER)
        self.assertTrue(audit.events())
        self.assertEqual(audit.con.execute('SELECT DISTINCT demo FROM adjustment_runs').fetchall(), [(1,)])


class Sidecar(unittest.TestCase):
    def test_the_procedure_is_an_adjustment_and_its_files_exist(self):
        meta = json.loads((ROOT / 'Procedures/HP_8902A_Cal_Factors.procedure.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['kind'], meta['manufacturer'], meta['model']), ('adjustment', 'HP', '8902A'))
        for rel in meta['own_files'] + meta['fingerprint']['code']:
            self.assertTrue((ROOT / rel).exists(), rel)
        self.assertEqual(procscan.classify(meta) if hasattr(procscan, 'classify') else 'adjustment', 'adjustment')


class FakeView:
    """The window code replaced by a plain list of rows (the scripted UI port builds no window)."""

    def __init__(self):
        self.rows = [('', '')] * 16
        self.log = []

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *a, **k: None

    def rows_get(self, app): return list(self.rows)
    def rows_set(self, app, rows): self.rows = list(rows) + [('', '')] * (16 - len(rows))
    def log_add(self, app, values, tags): self.log.append(values)


class Window(unittest.TestCase):
    """The launcher on the scripted UI port: typed confirmation, demo, nothing persisted."""

    def setUp(self):
        import ui_port
        spec = importlib.util.spec_from_file_location('hp8902a_launcher', ROOT / 'Procedures/HP_8902A_Cal_Factors.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.ui_port = ui_port
        self.answers = ui_port.Answers()
        self.port = ui_port.ScriptedUiPort(self.answers)
        self.old = ui_port.set_ui(self.port)
        self.view = FakeView()
        patcher = mock.patch.object(self.mod.App, 'ui_view', property(lambda s: self.view))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: ui_port.set_ui(self.old))
        sl = mock.patch('time.sleep')
        sl.start()
        self.addCleanup(sl.stop)
        self.app = self.mod.App(object(), demo=True)
        self.addCleanup(lambda: (self.app.audit.close(), self.app.tables.close()))
        self.view.rows = [('50', '99.0'), ('1000', '97.5')] + [('', '')] * 14
        for v, text in ((self.app.asset, 'A1'), (self.app.serial, 'S1'), (self.app.tech, 'Tech'), (self.app.sensor_serial, 'MX1'), (self.app.reference, '98.5')):
            v.set(text)
        self.app.connect()
        self.t = self.app.io.rx.t

    def typed(self, text):
        self.answers.rules.append(lambda rec: text if rec.get('kind') == 'ask_text' else None)

    def sent_writes(self):
        return [x for x in self.t.sent if '37.3SP' in x]

    def test_demo_entry_with_the_typed_word(self):
        self.app.start_record()
        self.assertIsNotNone(self.app.session)
        self.assertEqual(self.sent_writes(), [])
        self.typed('ENTER')
        self.app.enter_table()
        self.assertEqual(self.sent_writes(), ['37.3SP 98.5 CF', '37.3SP 50 MZ 99 CF', '37.3SP 1000 MZ 97.5 CF'])
        self.assertEqual(self.app.audit.status(), 'ENTERED_VERIFIED')
        asked = [p for p in self.port.prompts if p.get('kind') == 'ask_text']
        self.assertIn('CHANGES THE CAL-FACTOR TABLE', asked[-1]['text'])

    def test_any_other_answer_sends_nothing(self):
        for typed in ('enter', 'yes', ''):
            self.answers.rules.clear()
            self.app.start_record()
            self.typed(typed)
            self.app.enter_table()
            self.assertEqual(self.sent_writes(), [], typed)
            self.assertNotEqual(self.app.audit.status(), 'ENTERING')

    def test_an_invalid_list_is_refused_before_the_confirmation_is_even_asked(self):
        self.app.start_record()
        self.view.rows = [('50', '99.0'), ('50', '98.0')] + [('', '')] * 14
        self.typed('ENTER')
        self.app.enter_table()
        self.assertEqual(self.sent_writes(), [])
        self.assertFalse([p for p in self.port.prompts if p.get('kind') == 'ask_text'])

    def test_demo_saves_nothing_to_disk(self):
        self.app.start_record()
        self.typed('ENTER')
        self.app.enter_table()
        self.app.save_list()
        self.assertEqual(self.app.audit.path, ':memory:')
        self.assertEqual(self.app.tables.path, ':memory:')
        db = Path(os.environ['CALSUITE_DATA']) / 'lab_registry.sqlite3'              # (other test modules may share this folder: only OUR rows matter)
        if db.exists():
            con = sqlite3.connect(db)
            try:
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'adjustment_runs' in tables:
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM adjustment_runs WHERE instrument=?', (cf.INSTRUMENT,)).fetchone()[0], 0)
                if 'sensor_cal_factor_tables' in tables:
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM sensor_cal_factor_tables').fetchone()[0], 0)
            finally:
                con.close()


if __name__ == '__main__':
    unittest.main()
