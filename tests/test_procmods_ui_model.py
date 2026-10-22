"""procmods_ui_model: the UI-free controller of the 'Modify procedure' window.  No tkinter."""
import json
import tempfile
import unittest
from pathlib import Path

import cmdreg
import devmode
import procmods as pm
import procspec
import procmods_ui_model as M
from cmdreg import Cmd, Placeholder as P

ROOT = Path(__file__).resolve().parent.parent
procspec._fmt = lambda v, u: f'{v:g} {u}'

NPLC = Cmd('VOLT:DC:NPLC {nplc:g}', 'Set NPLC', placeholders={'nplc': P('float', 'g', 10.0)}, kind='set', readback='nplc?', verified=True)
NPLCQ = Cmd('VOLT:DC:NPLC?', 'Read NPLC', kind='query', verified=True)
RANGEQ = Cmd('VOLT:DC:RANG?', 'Read range', kind='query', verified=False)
OPER = Cmd('OPER', 'Operate', kind='action', risk='output')
REG = {'nplc': NPLC, 'nplc?': NPLCQ, 'range?': RANGEQ, 'oper': OPER}
pm.register_param('settle', 'float', 0, 120, affects_conditions=True, per_point=True, label='Settle time (s)', unit='s')


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = Clock()
        self.dm = devmode.DevMode(self.dir / 'dev.json', clock=self.clock, wall=self.clock, iterations=1000)
        self.lock = M.DevLock(self.dm)
        self.store = pm.Store(self.dir / 'lab.sqlite3', devmode=self.dm)
        spec = procspec.load(ROOT / 'specs' / 'keysight_34465a_pv.json')
        self.points = procspec.flatten(spec)
        procspec.apply_period(self.points, spec['default_period'])
        self.keys = pm.point_keys(self.points)
        self.calls = []
        self.running = False
        self.idn = 'KEYSIGHT,34465A,1,2'
        self.run_entries = []
        self.ctx = M.Context(title='34465A', model='34465A', asset_id='A1', registries={'ScpiDmm': REG}, points=self.points,
                             defaults={'settle': 1.0}, texts={'setup:p1': 'Connect the leads.', 'prompt:safety_hv': 'HV!'},
                             store=self.store, idn=lambda: self.idn, test_command=self.hook, is_running=lambda: self.running,
                             author='tester', run_entries=self.run_entries)
        self.model = M.ProcModsModel(self.ctx, self.lock)

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, driver, key, text):
        self.calls.append((driver, key, text))
        return {'ok': True, 'reply': '10', 'errors': '+0,"No error"', 'idn': self.idn}

    def unlock(self):
        self.assertTrue(self.lock.first_use('correct horse', 'correct horse').ok)


class LockTests(Base):
    def test_read_only_until_unlocked(self):
        m = self.model
        self.assertFalse(m.editable)
        self.assertIn('Unlock developer mode', m.read_only_reason)
        for fn in (lambda: m.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}'), lambda: m.stage_param('settle', 3),
                   lambda: m.stage_skip(self.keys[0]), lambda: m.stage_text('setup:p1', 'x'), lambda: m.apply(),
                   lambda: m.export(self.dir / 'x.json')):
            with self.assertRaises(pm.OverrideError):
                fn()
        self.assertEqual(self.store.entries(), [])

    def test_first_use_flow(self):
        self.assertEqual(self.lock.state, 'unset')
        r = self.lock.first_use('short', 'short')
        self.assertFalse(r.ok)
        self.assertFalse(self.lock.first_use('correct horse', 'different one').ok)
        r = self.lock.first_use('correct horse', 'correct horse')
        self.assertTrue(r.ok)
        self.assertEqual(self.lock.state, 'unlocked')
        self.assertTrue(self.model.editable)
        self.assertFalse(self.lock.first_use('correct horse', 'correct horse').ok)        # already set

    def test_idle_auto_lock_15_minutes(self):
        self.unlock()
        seen = []
        self.lock.on_change(seen.append)
        self.clock.t += 14 * 60
        self.assertEqual(self.lock.poll(), 'unlocked')
        self.clock.t += 2 * 60
        self.assertEqual(self.lock.poll(), 'locked')
        self.assertIn('locked', seen)
        self.assertFalse(self.model.editable)
        r = self.lock.unlock('correct horse')
        self.assertTrue(r.ok)
        self.assertTrue(self.model.editable)

    def test_activity_extends_the_session(self):
        self.unlock()
        for _ in range(4):
            self.clock.t += 10 * 60
            self.model.stage_param('settle', 3)               # a staged edit counts as activity
        self.assertTrue(self.lock.unlocked)

    def test_lockout_delay_shown(self):
        self.unlock()
        self.lock.lock()
        for _ in range(3):
            r = self.lock.unlock('wrong passphrase')
        self.assertFalse(r.ok)
        self.assertGreater(r.wait_s, 0)
        self.assertEqual(self.lock.state, 'lockout')
        self.assertIn('Try again in', self.lock.lockout_text())
        r = self.lock.unlock('correct horse')                   # even the right one waits
        self.assertFalse(r.ok)
        self.assertEqual(r.state, 'lockout')
        self.clock.t += 60
        self.assertEqual(self.lock.state, 'locked')
        self.assertTrue(self.lock.unlock('correct horse').ok)

    def test_passphrase_never_in_messages_or_logs(self):
        import logging
        pw = 'zebra-unique-passphrase-123'
        with self.assertLogs(level='DEBUG') as cm:
            logging.getLogger().debug('probe')
            results = [self.lock.first_use(pw, pw)]
            self.lock.lock()
            results += [self.lock.unlock(pw + 'x'), self.lock.unlock(pw)]
        text = ' '.join(cm.output) + ' '.join(r.message for r in results) + repr(vars(self.lock)) + repr(vars(self.model))
        self.assertNotIn(pw, text)
        self.assertNotIn(pw, (self.dir / 'dev.json').read_text())

    def test_running_makes_it_read_only(self):
        self.unlock()
        self.running = True
        self.assertEqual(self.model.read_only_reason, 'A run is in progress. Stop the run to edit.')
        with self.assertRaises(pm.OverrideError):
            self.model.stage_param('settle', 3)
        self.running = False
        self.assertTrue(self.model.editable)


class CommandTests(Base):
    def setUp(self):
        super().setUp()
        self.unlock()

    def test_detail_factory_vs_current_and_badges(self):
        d = self.model.command_detail('ScpiDmm:nplc')
        self.assertEqual((d['factory'], d['current']), ('VOLT:DC:NPLC {nplc:g}',) * 2)
        self.assertTrue(d['editable'])
        self.assertEqual(d['paired'], 'VOLT:DC:NPLC?')
        self.assertEqual(d['badges'], [])
        self.assertIn('!', self.model.command_detail('ScpiDmm:range?')['badges'])      # manual-unverified
        self.assertIn('Not yet tested', d['status'])

    def test_locked_output_key_not_editable_with_reason(self):
        d = self.model.command_detail('ScpiDmm:oper')
        self.assertFalse(d['editable'])
        self.assertIn('output', d['lock_reason'])
        self.assertIn('lock', d['badges'])
        chk = self.model.stage_command('ScpiDmm:oper', 'OUTP ON')
        self.assertFalse(chk.valid)
        self.assertEqual(self.model.drafts, {})

    def test_validation_messages_from_cmdreg(self):
        for bad, code in (('*RST', 0), ('VOLT:DC:NPLC {bogus}', 0), ('VOLT:DC:NPLC', 0), ('VOLT:DC:NPLC {nplc:g};OUTP ON', 0)):
            chk = self.model.stage_command('ScpiDmm:nplc', bad)
            self.assertFalse(chk.valid, bad)
            self.assertTrue(chk.problems[0])
            self.assertEqual(self.model.drafts, {})
        self.assertIn('Valid.', self.model.command_status('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}'))

    def test_stage_undo_and_factory_text_clears_draft(self):
        self.assertTrue(self.model.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}').valid)
        self.assertTrue(self.model.dirty)
        self.assertTrue(self.model.command_detail('ScpiDmm:nplc')['draft'])
        self.model.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC {nplc:g}')
        self.assertFalse(self.model.dirty)
        self.model.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}')
        self.model.undo('command', 'ScpiDmm:nplc')
        self.assertFalse(self.model.dirty)

    def test_apply_requires_reason_and_writes_once(self):
        m = self.model
        m.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}')
        with self.assertRaises(pm.OverrideError):
            m.apply()
        m.set_reason('command', 'ScpiDmm:nplc', '   ')
        with self.assertRaises(pm.OverrideError):
            m.apply()
        m.set_reason('command', 'ScpiDmm:nplc', 'firmware 3.x')
        r = m.apply()
        self.assertTrue(r.ok, r.errors)
        self.assertEqual(m.modified_count(), 1)                            # run scope: in memory
        self.assertEqual(self.store.entries(), [])
        self.assertEqual(m.chip(), 'MODIFIED (1)')
        self.assertEqual(m.command_detail('ScpiDmm:nplc')['current'], 'VOLT:DC:NPLC2 {nplc:g}')
        self.assertEqual(self.ctx.run_entries[0]['scope'], 'run')

    def test_asset_scope_needs_confirmation_then_persists(self):
        m = self.model
        m.set_scope('asset')
        m.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}')
        m.set_reason('command', 'ScpiDmm:nplc', 'fw')
        with self.assertRaises(M.NeedsConfirmation) as cm:
            m.apply()
        self.assertEqual(len(cm.exception.items), 1)
        self.assertEqual(self.store.entries(), [])
        self.assertTrue(m.apply(confirmed=True).ok)
        e = self.store.entries()[0]
        self.assertEqual((e['scope'], e['asset_id'], e['author']), ('asset', 'A1', 'tester'))
        self.assertEqual(M.count_for_model(self.store, '34465A', 'A1'), 1)
        self.assertEqual(M.count_for_model(self.store, '34465A', 'other'), 0)

    def test_edit_existing_then_reset_keeps_audit_trail(self):
        m = self.model
        m.set_scope('model')
        m.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}'); m.set_reason('command', 'ScpiDmm:nplc', 'one')
        m.apply(confirmed=True)
        m.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC3 {nplc:g}'); m.set_reason('command', 'ScpiDmm:nplc', 'two')
        m.apply(confirmed=True)
        heads = self.store.entries()
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0]['version'], 2)
        m.stage_reset('command', 'ScpiDmm:nplc'); m.set_reason('command', 'ScpiDmm:nplc', 'back')
        self.assertEqual(m.pending()[0]['action'], 'reset')
        self.assertTrue(m.apply().ok)                                       # a reset needs no scope confirmation
        self.assertEqual(m.modified_count(), 0)
        self.assertEqual(len(self.store.entries(heads_only=False)), 2)      # rows stay
        m.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC4 {nplc:g}'); m.set_reason('command', 'ScpiDmm:nplc', 'again')
        self.assertTrue(m.apply(confirmed=True).ok)                         # re-enables the disabled chain instead of failing
        self.assertEqual(m.command_detail('ScpiDmm:nplc')['current'], 'VOLT:DC:NPLC4 {nplc:g}')

    def test_run_entry_reset_and_reset_all(self):
        m = self.model
        m.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}'); m.set_reason('command', 'ScpiDmm:nplc', 'r')
        m.stage_param('settle', 4); m.set_reason('param', 'settle', 'r')
        m.apply()
        self.assertEqual(m.modified_count(), 2)
        self.assertEqual(m.stage_reset_all(), 2)
        for it in m.pending():
            m.set_reason(it['kind'], it['target'], 'reset')
        m.apply()
        self.assertEqual(m.modified_count(), 0)
        self.assertEqual(self.ctx.run_entries, [])

    def test_failed_item_stays_staged_and_is_not_retried(self):
        m = self.model
        m.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}'); m.set_reason('command', 'ScpiDmm:nplc', 'r')
        calls = []
        orig = pm.make_run_entry
        pm.make_run_entry = lambda *a, **k: (calls.append(1), (_ for _ in ()).throw(pm.OverrideError('disk full')))[1]
        try:
            r = m.apply()
        finally:
            pm.make_run_entry = orig
        self.assertEqual(len(calls), 1)
        self.assertFalse(r.ok)
        self.assertIn('disk full', r.errors[0][1])
        self.assertTrue(m.dirty)

    def test_cancel_discards(self):
        self.model.stage_command('ScpiDmm:nplc', 'VOLT:DC:NPLC2 {nplc:g}')
        self.model.cancel()
        self.assertFalse(self.model.dirty)


class TestCommandTests(Base):
    def setUp(self):
        super().setUp()
        self.unlock()

    def test_query_test_runs_once_and_marks_tested(self):
        m = self.model
        m.stage_command('ScpiDmm:range?', 'VOLT:DC:RANG:AUTO?')
        res = m.test_command('ScpiDmm:range?', 'VOLT:DC:RANG:AUTO?')
        self.assertTrue(res['ok'])
        self.assertEqual(self.calls, [('ScpiDmm', 'range?', 'VOLT:DC:RANG:AUTO?')])
        self.assertIn('Tested OK', m.command_detail('ScpiDmm:range?')['status'])
        m.stage_command('ScpiDmm:range?', 'VOLT:DC:RANG:AUTO?')
        self.assertIsNotNone(m.drafts[('command', 'ScpiDmm:range?')].tested)
        m.test_command('ScpiDmm:range?', 'VOLT:DC:RANG:AUTO?')
        self.assertEqual(len(self.calls), 2)                              # only when the technician presses again

    def test_edit_after_test_is_untested(self):
        m = self.model
        m.stage_command('ScpiDmm:range?', 'VOLT:DC:RANG:AUTO?'); m.test_command('ScpiDmm:range?', 'VOLT:DC:RANG:AUTO?')
        self.assertTrue(m.command_detail('ScpiDmm:range?')['tested'])
        self.assertNotIn('Tested OK', m.command_status('ScpiDmm:range?', 'VOLT:DC:RANG:UPP?'))
        m.stage_command('ScpiDmm:range?', 'VOLT:DC:RANG:UPP?')
        self.assertIsNone(m.drafts[('command', 'ScpiDmm:range?')].tested)

    def test_refusals(self):
        m = self.model
        self.assertFalse(m.can_test('ScpiDmm:nplc')[0])                     # a set, not a query
        self.assertFalse(m.can_test('ScpiDmm:oper')[0])
        self.assertFalse(m.test_command('ScpiDmm:oper')['ok'])
        self.idn = None
        self.assertEqual(m.can_test('ScpiDmm:range?')[1], 'No instrument is connected.')
        self.idn = 'X'
        self.ctx.demo = True
        self.assertEqual(m.can_test('ScpiDmm:range?')[1], 'Not available in demo mode.')
        self.ctx.demo = False
        self.ctx.test_command = None
        self.assertFalse(m.can_test('ScpiDmm:range?')[0])
        self.assertEqual(self.calls, [])

    def test_read_only_cannot_test(self):
        self.lock.lock()
        self.assertFalse(self.model.can_test('ScpiDmm:range?')[0])

    def test_instrument_error_and_exception_are_shown_not_retried(self):
        m = self.model
        self.ctx.test_command = lambda d, k, t: (self.calls.append(1), {'ok': True, 'reply': '', 'errors': '-113,"Undefined header"'})[1]
        r = m.test_command('ScpiDmm:range?', 'VOLT:DC:BAD?')
        self.assertFalse(r['ok'])
        self.assertIn('Undefined header', r['message'])
        self.assertEqual(len(self.calls), 1)
        def boom(*a):
            self.calls.append(2)
            raise RuntimeError('timeout')
        self.ctx.test_command = boom
        r = m.test_command('ScpiDmm:range?', 'VOLT:DC:BAD?')
        self.assertFalse(r['ok'])
        self.assertEqual(self.calls, [1, 2])

    def test_invalid_text_is_not_sent(self):
        r = self.model.test_command('ScpiDmm:range?', '*RST')
        self.assertFalse(r['ok'])
        self.assertEqual(self.calls, [])


class OtherTabTests(Base):
    def setUp(self):
        super().setUp()
        self.unlock()

    def test_settings(self):
        m = self.model
        self.assertEqual(m.stage_param('settle', 500), ['settle: must be between 0 and 120'])
        self.assertEqual(m.stage_param('nope', 1)[0], "unknown setting 'nope'")
        self.assertEqual(m.stage_param('settle', 1.0), [])                    # equals factory: no draft
        self.assertFalse(m.dirty)
        self.assertEqual(m.stage_param('settle', 8), [])
        m.set_reason('param', 'settle', 'slow DUT')
        m.apply()
        row = m.settings()[0]
        self.assertEqual((row['factory'], row['current'], row['state']), (1.0, 8, 'modified'))
        self.assertTrue(row['affects_conditions'])
        self.assertEqual(m.settings(filter='modified')[0]['key'], 'settle')

    def test_points_skip(self):
        m = self.model
        k = self.keys[0]
        self.assertEqual(m.stage_skip(k), [])
        m.set_reason('point', k, 'not fitted'); m.apply()
        self.assertTrue(next(r for r in m.points() if r['key'] == k)['skip'])
        self.assertEqual(m.stage_skip(k, False), [])                         # un-skip stages a reset
        self.assertEqual(m.pending()[0]['action'], 'reset')
        self.assertEqual(m.stage_skip('nope'), ['unknown point'])

    def test_text_and_locked_prompt(self):
        m = self.model
        self.assertEqual(m.stage_text('setup:p1', 'Use the short leads.'), [])
        m.set_reason('text', 'setup:p1', 'lab practice'); m.apply()
        rows = {r['key']: r for r in m.texts()}
        self.assertEqual(rows['setup:p1']['current'], 'Use the short leads.')
        self.assertTrue(rows['prompt:safety_hv']['locked'])
        self.assertEqual(rows['prompt:safety_hv']['lock_reason'], 'Safety prompt: locked')
        self.assertTrue(m.stage_text('prompt:safety_hv', 'nothing'))
        self.assertEqual([r['key'] for r in m.texts(filter='locked')], ['prompt:safety_hv'])

    def test_tolerances_band_or_error(self):
        m = self.model
        rows = m.tolerances()
        self.assertTrue(rows)
        r = rows[0]
        p = self.points[self.keys.index(r['key'])]
        self.assertTrue(m.stage_limit(r['key'], low='x', high='y'))
        if r['mode'] == 'error':
            self.assertEqual(m.stage_limit(r['key'], error=float(p['error']) * 2), [])
        else:
            hi = float(p['high']) * 2 if float(p['high']) else 1.0
            self.assertEqual(m.stage_limit(r['key'], low=p['low'], high=hi), [])
        m.set_reason('limit', r['key'], 'customer tolerance')
        self.assertTrue(m.apply().ok)
        r2 = next(x for x in m.tolerances() if x['key'] == r['key'])
        self.assertEqual(r2['state'], 'modified')
        self.assertNotEqual(r2['factory'], r2['current'])
        self.assertTrue(self.model.oset.has_limits)
        # the factory point list was not touched
        self.assertEqual(pm.limit_factory(self.points[self.keys.index(r['key'])]), pm.limit_factory(p))

    def test_changes_tab_and_counts(self):
        m = self.model
        m.stage_param('settle', 8); m.set_reason('param', 'settle', 'r')
        m.stage_command('ScpiDmm:range?', 'VOLT:DC:RANG:AUTO?'); m.set_reason('command', 'ScpiDmm:range?', 'r')
        m.apply()
        ch = m.changes()
        self.assertEqual({c['kind'] for c in ch}, {'param', 'command'})
        self.assertTrue(any('!' in c['badges'] for c in ch if c['kind'] == 'command'))   # untested edit is UNVERIFIED
        self.assertEqual(m.tab_counts()['Changes'], 2)
        self.assertEqual(m.tab_counts()['Commands'], 1)

    def test_visible_tabs_manager_mode(self):
        mgr = M.ProcModsModel(M.Context(model='34465A', store=self.store), self.lock)
        self.assertEqual(mgr.visible_tabs(), ['Changes'])
        self.assertIn('Commands', self.model.visible_tabs())

    def test_filters_and_search(self):
        m = self.model
        self.assertEqual([r['key'] for r in m.commands(filter='locked')], ['oper'])
        self.assertEqual([r['key'] for r in m.commands(filter='unverified')], ['range?'])
        self.assertEqual([r['key'] for r in m.commands(search='read range')], ['range?'])


class ImportExportTests(Base):
    def setUp(self):
        super().setUp()
        self.unlock()

    def _make(self):
        m = self.model
        m.set_scope('model')
        m.stage_param('settle', 8); m.set_reason('param', 'settle', 'slow')
        m.apply(confirmed=True)

    def test_export_requires_unlock_and_round_trips(self):
        self._make()
        path = self.dir / 'out.calov.json'
        self.model.export(path)
        data = json.loads(path.read_text())
        self.assertEqual(data['format'], 'calov')
        self.assertEqual(len(data['entries']), 1)
        self.lock.lock()
        with self.assertRaises(pm.OverrideError):
            self.model.export(self.dir / 'no.json')
        self.assertFalse((self.dir / 'no.json').exists())

        other = pm.Store(self.dir / 'other.sqlite3', devmode=self.dm)
        self.unlock_again = self.lock.unlock('correct horse')
        m2 = M.ProcModsModel(M.Context(model='34465A', store=other, defaults={'settle': 1.0}), self.lock)
        prev = m2.import_preview(path)
        lines = m2.preview_lines(prev)
        self.assertEqual([(l['state'], l['accept']) for l in lines], [('new', True)])
        created = m2.import_apply(prev)
        self.assertEqual(len(created), 1)
        self.assertEqual(m2.modified_count(), 1)
        self.assertEqual(m2.preview_lines(m2.import_preview(path))[0]['state'], 'identical')

    def test_tampered_file_and_garbage_rejected(self):
        self._make()
        path = self.dir / 'out.json'
        self.model.export(path)
        data = json.loads(path.read_text()); data['entries'][0]['reason'] = 'edited'
        path.write_text(json.dumps(data))
        self.assertFalse(self.model.import_preview(path)['ok'])
        junk = self.dir / 'junk.json'; junk.write_text('not json')
        self.assertFalse(self.model.import_preview(junk)['ok'])

    def test_import_needs_unlock(self):
        self._make()
        path = self.dir / 'o.json'; self.model.export(path)
        prev = self.model.import_preview(path)
        self.lock.lock()
        with self.assertRaises(pm.OverrideError):
            self.model.import_apply(prev)


class SmallHelperTests(unittest.TestCase):
    def test_chips_and_badges(self):
        self.assertEqual(M.chip_text(0), '')
        self.assertEqual(M.chip_text(3), 'MODIFIED (3)')
        self.assertEqual(M.devmode_chip_text(True), 'DEVELOPER MODE')
        self.assertEqual(M.devmode_chip_text(False), '')
        self.assertEqual(M.row_badges({'state': 'modified', 'unverified': True, 'locked': False}), ['M', '!'])
        self.assertEqual(M.row_badges({'state': 'locked', 'locked': True}), ['lock'])


if __name__ == '__main__':
    unittest.main()
