"""procmods + devmode: store, developer-mode gate, precedence, limits guard, snapshots, import/export.  No tkinter."""
import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import cmdreg
import devmode
import procmods as pm
import procspec
from cmdreg import Cmd, Placeholder as P

ROOT = Path(__file__).resolve().parent.parent
procspec._fmt = lambda v, u: f'{v:g} {u}'                        # procspec.describe needs tkinter for SI scaling: stub for the headless tests

NPLC = Cmd('VOLT:DC:NPLC {nplc:g}', 'Set NPLC', placeholders={'nplc': P('float', 'g', 10.0)}, kind='set', readback='nplc?', verified=True)
NPLCQ = Cmd('VOLT:DC:NPLC?', 'Read NPLC', kind='query', verified=True)
OPER = Cmd('OPER', 'Operate', kind='action', risk='output')
REG = {'nplc': NPLC, 'nplc?': NPLCQ, 'oper': OPER}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = Clock()
        self.dm = devmode.DevMode(self.dir / 'dev' / 'devmode.json', clock=self.clock, wall=self.clock, iterations=1000)
        self.session = self.dm.set_passphrase('correct horse')
        self.db = self.dir / 'lab_registry.sqlite3'
        self.store = pm.Store(self.db, devmode=self.dm)
        self.points = self.spec_points('keysight_34465a_pv.json')

    def tearDown(self):
        self.tmp.cleanup()

    def spec_points(self, name):
        pts = procspec.flatten(procspec.load(ROOT / 'specs' / name))
        procspec.apply_period(pts, procspec.load(ROOT / 'specs' / name)['default_period'])
        return pts

    def add_nplc(self, scope='model', **kw):
        kw.setdefault('model', '34465A')
        return self.store.add('command', 'ScpiDmm:nplc', {'template': 'VOLT:DC:NPLC2 {nplc:g}'}, scope, 'fw 3.x', cmd=NPLC,
                              session=self.session, author='tester', **kw)


class DevModeTests(Base):
    def test_first_use_unlock_and_file(self):
        dm = devmode.DevMode(self.dir / 'x' / 'd.json', clock=self.clock, wall=self.clock, iterations=1000)
        self.assertFalse(dm.is_set())
        with self.assertRaises(devmode.DevModeError):
            dm.set_passphrase('short')
        s = dm.set_passphrase('longenough1')
        self.assertTrue(dm.is_set() and s.valid())
        text = (self.dir / 'x' / 'd.json').read_text()
        self.assertNotIn('longenough1', text)
        data = json.loads(text)
        self.assertEqual(set(data) >= {'salt', 'hash', 'iterations', 'device_key'}, True)
        with self.assertRaises(devmode.DevModeError):
            dm.set_passphrase('another-one-1')
        with self.assertRaises(devmode.BadPassphrase):
            dm.unlock('wrong')
        self.assertTrue(dm.unlock('longenough1').valid())

    def test_idle_timeout_and_explicit_lock(self):
        s = self.dm.unlock('correct horse')
        self.clock.t += 14 * 60
        self.assertTrue(s.valid())
        self.assertTrue(s.touch())                      # activity restarts the timer
        self.clock.t += 14 * 60
        self.assertTrue(s.valid())
        self.clock.t += 2 * 60
        self.assertFalse(s.valid())
        self.assertFalse(s.touch())                     # stays locked
        s2 = self.dm.unlock('correct horse')
        s2.lock()
        self.assertFalse(s2.valid())

    def test_lockout_after_repeated_failures(self):
        for _ in range(3):
            with self.assertRaises(devmode.BadPassphrase):
                self.dm.unlock('nope')
        with self.assertRaises(devmode.LockedOut) as cm:
            self.dm.unlock('correct horse')              # even the right one is refused during the delay
        self.assertGreater(cm.exception.wait_s, 0)
        self.clock.t += 6
        self.assertTrue(self.dm.unlock('correct horse').valid())
        for _ in range(4):                               # delay grows
            try:
                self.dm.unlock('nope')
            except devmode.DevModeError:
                self.clock.t += 400
        self.assertTrue(self.dm.unlock('correct horse').valid())

    def test_no_secret_in_store_or_files(self):
        self.add_nplc()
        blob = self.db.read_bytes() + (self.dir / 'dev' / 'devmode.json').read_bytes()
        self.assertNotIn(b'correct horse', blob)


class GateTests(Base):
    """Every mutation is refused without a valid session and allowed with one; applying stays free."""

    def test_mutations_refused_without_session(self):
        e = self.add_nplc()
        locked = self.dm.unlock('correct horse')
        locked.lock()
        p = self.points[0]
        tries = [
            lambda s: self.store.add('param', 'delay', {'value': 1}, 'model', 'r', model='M', session=s),
            lambda s: self.store.add('point', pm.point_key(p), {}, 'asset', 'r', asset_id='A1', point=p, session=s),
            lambda s: self.store.add('text', 'note:' + pm.point_key(p), {'text': 'hello'}, 'model', 'r', model='M', session=s),
            lambda s: self.store.add('limit', pm.point_key(p), {'mode': 'error', 'error': '0.5'}, 'model', 'r', model='M', point=p, session=s),
            lambda s: self.store.edit(e['uid'], value={'template': 'VOLT:DC:NPLC3 {nplc:g}'}, reason='r', cmd=NPLC, session=s),
            lambda s: self.store.set_enabled(e['uid'], False, session=s),
            lambda s: self.store.set_enabled(e['uid'], True, session=s),
            lambda s: self.store.reset(e['uid'], session=s),
            lambda s: pm.make_run_entry('param', 'delay', {'value': 1}, 'r', session=s),
            lambda s: pm.export_entries(self.store, self.dir / 'x.calov.json', session=s),
        ]
        for i, t in enumerate(tries):
            for bad in (None, locked, 'yes', object()):
                with self.assertRaises(pm.OverrideError, msg=f'call {i} / {bad!r}'):
                    t(bad)
        rows_before = len(self.store.entries(heads_only=False))
        self.assertEqual(rows_before, 1)
        self.assertTrue(self.store.get(e['uid'])['enabled'])
        # import apply
        payload, _ = pm.export_entries(self.store, session=self.session)
        prev = pm.import_preview(self.store, payload, registries={'ScpiDmm': REG})          # preview needs no session and applies nothing
        with self.assertRaises(pm.OverrideError):
            pm.apply_import(self.store, prev, session=locked)

    def test_allowed_with_session_including_run_scope_and_session_of_other_file(self):
        self.add_nplc()
        r = pm.make_run_entry('param', 'delay', {'value': 1.5}, 'bench is slow', session=self.session)
        self.assertEqual(r['scope'], 'run')
        other = devmode.DevMode(self.dir / 'o.json', clock=self.clock, wall=self.clock, iterations=1000).set_passphrase('another pass 1')
        with self.assertRaises(pm.OverrideError):
            self.store.add('param', 'delay', {'value': 1}, 'model', 'r', model='M', session=other)

    def test_apply_and_read_work_locked(self):
        pt = self.points[3]
        k = pm.point_key(pt)
        self.store.add('limit', k, {'mode': 'error', 'error': pt['error'] * 2}, 'model', 'wider', model='34465A', point=pt, session=self.session)
        self.store.add('point', pm.point_key(self.points[5]), {}, 'model', 'skip', model='34465A', point=self.points[5], session=self.session)
        self.session.lock()
        oset = pm.resolve('34465A', None, store=self.store)
        out = pm.apply_points(self.points, oset)
        self.assertEqual(out[3]['error'], pt['error'] * 2)
        self.assertTrue(out[5]['skip'])
        self.assertTrue(pm.modifications_summary(oset))
        self.assertTrue(pm.changes(oset))
        self.assertEqual(pm.resolve('34465A', None, store=self.store, factory_only=True).hash, '')
        snap = pm.build_snapshot(oset)
        self.assertTrue(pm.restore_snapshot(snap, devmode=self.dm))


class CommandTests(Base):
    def test_validation_on_add(self):
        for tpl in ('*RST', 'OPER', 'VOLT:DC:NPLC', 'VOLT:DC:NPLC {x}'):
            with self.assertRaises(pm.OverrideError, msg=tpl):
                self.store.add('command', 'ScpiDmm:nplc', {'template': tpl}, 'model', 'r', model='M', cmd=NPLC, session=self.session)
        with self.assertRaises(pm.OverrideError):                     # locked output command
            self.store.add('command', 'ScpiDmm:oper', {'template': 'OPER '}, 'model', 'r', model='M', cmd=OPER, session=self.session)
        with self.assertRaises(pm.OverrideError):                     # reason required
            self.store.add('command', 'ScpiDmm:nplc', {'template': 'VOLT:DC:NPLC2 {nplc:g}'}, 'model', '  ', model='M', cmd=NPLC, session=self.session)
        with self.assertRaises(pm.OverrideError):                     # run scope never stored
            self.store.add('command', 'ScpiDmm:nplc', {'template': 'VOLT:DC:NPLC2 {nplc:g}'}, 'run', 'r', cmd=NPLC, session=self.session)
        with self.assertRaises(pm.OverrideError):                     # no-op
            self.store.add('command', 'ScpiDmm:nplc', {'template': NPLC.template}, 'model', 'r', model='M', cmd=NPLC, session=self.session)
        self.assertEqual(self.store.entries(heads_only=False), [])

    def test_secret_not_overridable(self):
        sec = Cmd('CAL:SEC {pw}', 'x', placeholders={'pw': P('secret', '', 'x')})
        with self.assertRaises(pm.OverrideError):
            self.store.add('command', 'D:sec', {'template': 'STAT {pw}'}, 'model', 'r', model='M', cmd=sec, session=self.session)

    def test_commands_for_with_class_and_stale(self):
        class Base_:
            COMMANDS = {'nplc': NPLC, 'nplc?': NPLCQ}

        class Child(Base_):
            pass
        e = self.store.add('command', 'Base_:nplc', {'template': 'VOLT:DC:NPLC2 {nplc:g}'}, 'model', 'fw', model='M', cmd=NPLC,
                           session=self.session)
        oset = pm.resolve('M', None, store=self.store)
        self.assertEqual(oset.commands_for(Child), {'nplc': 'VOLT:DC:NPLC2 {nplc:g}'})       # applies through the MRO
        self.assertEqual(oset.commands_for('Base_'), {'nplc': 'VOLT:DC:NPLC2 {nplc:g}'})
        self.assertEqual(oset.commands_for('Other'), {})
        Base_.COMMANDS = {'nplc': Cmd('VOLT:DC:NPLC {nplc:g}x', 'Set NPLC', placeholders=NPLC.placeholders, readback='nplc?'),
                          'nplc?': NPLCQ}
        self.assertEqual(oset.commands_for(Child), {})
        self.assertEqual(oset.rejected_commands(Child)[0][0], e['uid'])

    def test_readback_bundle(self):
        class D:
            COMMANDS = {'nplc': NPLC, 'nplc?': NPLCQ}
        self.store.add('command', 'D:nplc?', {'template': 'VOLT:DC:NPLC2?'}, 'model', 'r', model='M', cmd=NPLCQ, session=self.session)
        self.assertEqual(pm.resolve('M', None, store=self.store).commands_for(D), {'nplc?': 'VOLT:DC:NPLC2?'})
        with self.assertRaises(pm.OverrideError):
            self.store.add('command', 'D:nplc?', {'template': 'VOLT:DC:NPLC2'}, 'asset', 'r', asset_id='A', cmd=NPLCQ, session=self.session)

    def test_fw_match(self):
        self.add_nplc(fw_match=r'A\.03')
        oset = pm.resolve('34465A', None, store=self.store)
        self.assertEqual(oset.commands_for('ScpiDmm'), {})
        self.assertEqual(oset.entries()[0]['status'], 'pending_fw')
        self.assertTrue(oset.with_idn('KEYSIGHT,34465A,MY1,A.03.02').commands_for('ScpiDmm'))
        self.assertEqual(oset.with_idn('KEYSIGHT,34465A,MY1,A.02.00').commands_for('ScpiDmm'), {})


class PrecedenceVersions(Base):
    def test_precedence_run_asset_model(self):
        a = lambda scope, v, **k: self.store.add('param', 'delay', {'value': v}, scope, 'r', session=self.session, **k)
        a('model', 1.0, model='M')
        self.assertEqual(pm.resolve('M', 'A1', store=self.store).param('delay', 0), 1.0)
        a('asset', 2.0, asset_id='A1', model='M')
        self.assertEqual(pm.resolve('M', 'A1', store=self.store).param('delay', 0), 2.0)
        self.assertEqual(pm.resolve('M', 'a1', store=self.store).param('delay', 0), 2.0)          # NOCASE
        self.assertEqual(pm.resolve('M', 'A2', store=self.store).param('delay', 0), 1.0)
        self.assertEqual(pm.resolve('OTHER', 'A2', store=self.store).param('delay', 0), 0)
        run = pm.make_run_entry('param', 'delay', {'value': 3.0}, 'now', session=self.session)
        o = pm.resolve('M', 'A1', run_overrides=[run], store=self.store)
        self.assertEqual(o.param('delay', 0), 3.0)
        self.assertEqual(sorted(e['status'] for e in o.entries()), ['active', 'shadowed', 'shadowed'])
        self.assertEqual(pm.resolve('M', 'A1', store=self.store, factory_only=True).param('delay', 0), 0)

    def test_append_only_versions(self):
        e1 = self.store.add('param', 'delay', {'value': 1.0}, 'model', 'first', model='M', session=self.session)
        e2 = self.store.edit(e1['uid'], value={'value': 2.0}, reason='second', session=self.session)
        self.assertEqual((e2['version'], e2['supersedes']), (2, e1['uid']))
        self.assertEqual(self.store.get(e1['uid'])['value']['value'], 1.0)                        # old row untouched
        self.assertEqual([x['version'] for x in self.store.history(e2['uid'])], [1, 2])
        self.assertEqual(len(self.store.entries()), 1)
        self.assertEqual(pm.resolve('M', None, store=self.store).param('delay'), 2.0)
        with self.assertRaises(pm.OverrideError):
            self.store.edit(e1['uid'], value={'value': 3.0}, reason='x', session=self.session)   # superseded
        with self.assertRaises(pm.OverrideError):
            self.store.add('param', 'delay', {'value': 5.0}, 'model', 'dup', model='M', session=self.session)
        con = sqlite3.connect(self.db)
        for sql in ("UPDATE override SET reason='x'", "UPDATE override SET value_json='{}'", "DELETE FROM override",
                    "UPDATE override_log SET who='x'", "DELETE FROM override_log"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                con.execute(sql)
        con.execute('UPDATE override SET enabled=0')                                              # allowed
        con.commit()
        con.close()
        self.assertEqual(pm.resolve('M', None, store=self.store).param('delay', 9), 9)
        self.assertTrue([r for r in self.store.log() if r['action'] == 'edit'])

    def test_enable_disable_and_expiry(self):
        e = self.store.add('param', 'delay', {'value': 1.0}, 'model', 'r', model='M', session=self.session, expires_at='2026-11-01')
        now = datetime(2026, 10, 22)
        self.assertEqual(pm.resolve('M', None, store=self.store, now=now).param('delay', 0), 1.0)
        o = pm.resolve('M', None, store=self.store, now=datetime(2026, 11, 2))
        self.assertEqual((o.param('delay', 0), o.entries()[0]['status']), (0, 'expired'))
        self.assertEqual(pm.resolve('M', None, store=self.store, now=datetime(2026, 11, 1, 23)).param('delay', 0), 1.0)
        self.store.set_enabled(e['uid'], False, session=self.session)
        self.assertEqual(pm.resolve('M', None, store=self.store, now=now).param('delay', 0), 0)

    def test_param_checks_and_stale_default(self):
        for name, v in (('nope', 1), ('delay', -1), ('delay', 'x'), ('settle.ac', 9999), ('nplc', True)):
            with self.assertRaises(pm.OverrideError, msg=name):
                self.store.add('param', name, {'value': v}, 'model', 'r', model='M', session=self.session)
        with self.assertRaises(pm.OverrideError):
            self.store.add('param', 'delay@x', {'value': 1}, 'model', 'r', model='M', session=self.session) if not pm.PARAMS['delay']['per_point'] else (_ for _ in ()).throw(pm.OverrideError('x'))
        self.store.add('param', 'settle.ac', {'value': 8}, 'model', 'r', model='M', factory=4, session=self.session)
        o = pm.resolve('M', None, store=self.store)
        self.assertEqual(o.param('settle.ac', 4), 8)
        self.assertEqual(o.param('settle.ac', 5), 5)                  # factory default changed: stale, not applied
        s = pm.modifications_summary(o)[0]
        self.assertTrue(s['affects_conditions'])

    def test_immutable(self):
        self.add_nplc()
        o = pm.resolve('34465A', None, store=self.store)
        with self.assertRaises(AttributeError):
            o.hash = 'x'
        o.entries()[0]['value']['template'] = 'tamper'
        self.assertNotEqual(o.entries()[0]['value']['template'], 'tamper')
        self.assertTrue(o.hash)
        self.assertEqual(pm.resolve('34465A', None, store=self.store).hash, o.hash)


class PointsAndLimits(Base):
    def test_keys_stable_and_not_positional(self):
        keys = pm.point_keys(self.points)
        self.assertEqual(len(set(keys)), len(keys))
        rev = pm.point_keys(list(reversed(self.points)))
        self.assertEqual(set(keys), set(rev))
        self.assertNotIn('id=', keys[0])

    def test_stale_when_spec_changes(self):
        p = self.points[4]
        k = pm.point_key(p)
        self.store.add('point', k, {}, 'model', 'skip it', model='M', point=p, session=self.session)
        self.store.add('text', 'setup:' + k, {'text': 'Use the short leads.'}, 'model', 'r', model='M', factory=p['setup'], session=self.session)
        o = pm.resolve('M', None, store=self.store)
        out = pm.apply_points(self.points, o)
        self.assertTrue(out[4]['skip'] and out[4]['setup'] == 'Use the short leads.' and out[4]['ov'])
        self.assertNotIn('skip', out[3])
        changed = copy.deepcopy(self.points)
        changed[4]['limits'] = {k2: v * 2 for k2, v in changed[4]['limits'].items()}               # spec rebuilt with other limits
        changed[4]['setup'] = 'different'
        chk = pm.check_points(changed, o)
        self.assertEqual(len(chk['stale']), 2)
        out2 = pm.apply_points(changed, o)
        self.assertNotIn('skip', out2[4])
        self.assertEqual(out2[4]['setup'], 'different')
        gone = [q for i, q in enumerate(self.points) if i != 4]
        self.assertEqual(len(pm.check_points(gone, o)['orphan']), 2)
        self.assertEqual([r['state'] for r in pm.point_rows(changed, o) if r['key'] == k], ['stale'])

    def test_per_point_param(self):
        p = self.points[2]
        k = pm.point_key(p)
        self.store.add('param', f'settle@{k}', {'value': 12}, 'asset', 'slow', asset_id='A1', session=self.session, factory=None)
        out = pm.apply_points(self.points, pm.resolve('M', 'A1', store=self.store))
        self.assertEqual(out[2]['settle'], 12)
        self.assertNotIn('settle', out[1])

    def test_limits_unchanged_for_every_non_limit_kind_on_real_specs(self):
        specs = [('keysight_34465a_pv.json', False), ('keysight_34470a_pv.json', False), ('fluke_80_series_v_pv.json', True),
                 ('klein_mm325_pv.json', True), ('tektronix_mdo4000c_pv.json', None), ('fluke_287_289_pv.json', True)]
        for name, steps in specs:
            spec = json.loads((ROOT / 'specs' / name).read_text(encoding='utf-8'))
            if steps is True:
                pts = spec['steps']
            elif steps is None:
                pts = spec['points'][:200]
            else:
                pts = self.spec_points(name)
            pts = pts[:60]
            store = pm.Store(self.dir / f'{name}.sqlite3', devmode=self.dm)
            for p in pts[::3]:
                k = pm.point_key(p)
                try:
                    store.add('point', k, {}, 'model', 'r', model='X', point=p, session=self.session)
                    store.add('text', 'note:' + k, {'text': 'note'}, 'model', 'r', model='X', session=self.session)
                    store.add('param', f'settle@{k}', {'value': 3}, 'model', 'r', model='X', session=self.session)
                except pm.OverrideError:
                    pass                                              # duplicate keys in a spec: fine
            o = pm.resolve('X', None, store=store)
            self.assertTrue(o, name)
            out = pm.apply_points(pts, o)
            self.assertTrue(any(q.get('skip') for q in out), name)
            for a, b in zip(pts, out):
                for f in pm.LIMIT_FIELDS:
                    self.assertEqual(json.dumps(a.get(f), sort_keys=True), json.dumps(b.get(f), sort_keys=True), (name, f))

    def test_guard_catches_foreign_changes(self):
        out = copy.deepcopy(self.points)
        out[1]['error'] = out[1]['error'] * 2
        with self.assertRaises(pm.LimitsChangedError):
            pm.assert_limits_unchanged(self.points, out)
        pm.assert_limits_unchanged(self.points, out, limit_ok={1})                               # only through a limit override
        out[1]['limits'] = {}
        with self.assertRaises(pm.LimitsChangedError):
            pm.assert_limits_unchanged(self.points, out, limit_ok={1})
        out = copy.deepcopy(self.points)
        out[0]['nominal'] += 1
        with self.assertRaises(pm.LimitsChangedError):
            pm.assert_limits_unchanged(self.points, out, limit_ok={0})
        out = copy.deepcopy(self.points)
        out[2]['surprise'] = 1
        with self.assertRaises(pm.LimitsChangedError):
            pm.assert_limits_unchanged(self.points, out)

    def test_limit_override_error_and_band(self):
        p = self.points[3]
        k = pm.point_key(p)
        e = self.store.add('limit', k, {'mode': 'error', 'error': p['error'] * 2}, 'asset', 'customer spec', asset_id='A1', model='34465A',
                           point=p, session=self.session, author='me')
        o = pm.resolve('34465A', 'A1', store=self.store)
        out = pm.apply_points(self.points, o)
        self.assertEqual(out[3]['error'], p['error'] * 2)
        self.assertTrue(out[3]['limit_modified'] and out[3]['limit_factory']['error'] == p['error'])
        self.assertEqual(out[3]['limits'], p['limits'])
        self.assertEqual(out[4]['error'], self.points[4]['error'])
        self.assertIsNone(pm.resolve('34465A', 'A2', store=self.store).limit_override(k))
        s = pm.modifications_summary(o)[0]
        self.assertTrue(s['limit'] and s['tolerances_modified'] and s['manufacturer_tolerance'] and s['tolerance_used'] != s['manufacturer_tolerance'])
        self.assertEqual((s['reason'], s['author']), ('customer spec', 'me'))
        self.assertTrue(pm.tolerances_modified(o))
        self.assertFalse(pm.tolerances_modified(pm.resolve('34465A', 'A2', store=self.store)))
        # period change -> factory error differs -> stale, not applied
        other = copy.deepcopy(self.points)
        other[3]['error'] = p['error'] * 3
        self.assertEqual(pm.apply_points(other, o)[3]['error'], p['error'] * 3)
        # bad values
        for v in ({'mode': 'error', 'error': 0}, {'mode': 'error', 'error': 'x'}, {'mode': 'band', 'low': 1, 'high': 2}, {'mode': 'error', 'error': self.points[6]['error']}):
            with self.assertRaises(pm.OverrideError, msg=str(v)):
                self.store.add('limit', pm.point_key(self.points[6]), v, 'model', 'r', model='34465A', point=self.points[6], session=self.session)
        # edit keeps a valid MAC
        e2 = self.store.edit(e['uid'], value={'mode': 'error', 'error': p['error'] * 4}, reason='again', point=p, session=self.session)
        self.assertEqual(pm.apply_points(self.points, pm.resolve('34465A', 'A1', store=self.store))[3]['error'], p['error'] * 4)
        self.assertEqual(e2['version'], 2)

    def test_limit_override_band_handheld_strings(self):
        steps = [s for s in json.loads((ROOT / 'specs' / 'fluke_80_series_v_pv.json').read_text(encoding='utf-8'))['steps'] if s['test'] == 'numeric'][:10]
        p = steps[0]
        k = pm.point_key(p)
        lo, hi = float(p['low']), float(p['high'])
        self.store.add('limit', k, {'mode': 'band', 'low': str(lo - 1), 'high': str(hi + 1)}, 'model', 'r', model='87V', point=p, session=self.session)
        out = pm.apply_points(steps, pm.resolve('87V', None, store=self.store))
        self.assertEqual((out[0]['low'], out[0]['high']), (str(lo - 1), str(hi + 1)))
        self.assertEqual(steps[0]['low'], p['low'])                                                # original untouched
        with self.assertRaises(pm.OverrideError):
            self.store.add('limit', pm.point_key(steps[1]), {'mode': 'band', 'low': '5', 'high': '1'}, 'model', 'r', model='87V', point=steps[1], session=self.session)

    def test_tamper_detection(self):
        p = self.points[3]
        k = pm.point_key(p)
        e = self.store.add('limit', k, {'mode': 'error', 'error': p['error'] * 2}, 'model', 'r', model='M', point=p, session=self.session)
        con = sqlite3.connect(self.db)
        # the append-only trigger blocks edits to the value; simulate casual tampering by replacing the table content
        con.execute('DROP TRIGGER override_append_only')
        con.execute("UPDATE override SET value_json=? WHERE uid=?", (json.dumps({**e['value'], 'error': 99.0}), e['uid']))
        con.commit()
        con.close()
        o = pm.resolve('M', None, store=self.store)
        self.assertEqual([x['status'] for x in o.entries()], ['tampered'])
        self.assertEqual(len(o.tampered()), 1)
        self.assertEqual(pm.apply_points(self.points, o)[3]['error'], p['error'])                   # not applied
        self.assertFalse(o)
        self.assertEqual(pm.modifications_summary(o), [])
        # also: no device key at all
        e2 = self.store.add('limit', pm.point_key(self.points[5]), {'mode': 'error', 'error': self.points[5]['error'] * 2}, 'model', 'r',
                            model='N', point=self.points[5], session=self.session)
        (self.dir / 'dev' / 'devmode.json').unlink()
        self.assertEqual([x['status'] for x in pm.resolve('N', None, store=self.store).entries()], ['tampered'])

    def test_run_scope_limit_needs_session_and_verifies(self):
        p = self.points[1]
        k = pm.point_key(p)
        run = pm.make_run_entry('limit', k, {'mode': 'error', 'error': p['error'] * 2}, 'r', point=p, session=self.session)
        o = pm.resolve('M', None, run_overrides=[run], store=self.store)
        self.assertEqual(pm.apply_points(self.points, o)[1]['error'], p['error'] * 2)
        bad = copy.deepcopy(run)
        bad['value']['error'] = 99
        self.assertEqual(pm.apply_points(self.points, pm.resolve('M', None, run_overrides=[bad], store=self.store))[1]['error'], p['error'])


class SnapshotsAndRun(Base):
    def test_run_scope_never_in_db(self):
        self.add_nplc()
        run = pm.make_run_entry('param', 'delay', {'value': 2.5}, 'UNIQUE-RUN-REASON-XYZ', session=self.session)
        pm.resolve('34465A', 'A1', run_overrides=[run], store=self.store)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT count(*) FROM override WHERE scope NOT IN ('model','asset')").fetchone()[0], 0)
        con.close()
        self.assertNotIn(b'UNIQUE-RUN-REASON-XYZ', self.db.read_bytes())
        self.assertEqual(set(r[0] for r in sqlite3.connect(self.db).execute("select name from sqlite_master where type='table'")) - {'sqlite_sequence'},
                         {'override', 'override_log', 'run_overrides'})

    def test_snapshot_round_trip_and_hash(self):
        self.add_nplc()
        run = pm.make_run_entry('param', 'delay', {'value': 2.5}, 'r', session=self.session)
        o = pm.resolve('34465A', 'A1', run_overrides=[run], store=self.store)
        snap = pm.build_snapshot(o, now=datetime(2026, 1, 1))
        self.assertEqual((len(snap['revs']), snap['revs'][0]['rev'], snap['hash']), (1, 1, o.hash))
        self.assertTrue(pm.verify_snapshot(snap))
        snap = json.loads(json.dumps(snap))
        back = pm.restore_snapshot(snap, devmode=self.dm)
        self.assertEqual(back.hash, o.hash)
        self.assertEqual(back.commands_for('ScpiDmm'), o.commands_for('ScpiDmm'))
        self.assertEqual(back.param('delay'), 2.5)
        self.assertEqual(pm.build_snapshot(o, prior=snap)['revs'], snap['revs'])                  # unchanged: no new revision
        self.assertTrue(pm.compare_with_current(snap, o)['same'])
        # hash change detection
        t = copy.deepcopy(snap)
        t['revs'][0]['entries'][0]['value']['template'] = 'X'
        self.assertFalse(pm.verify_snapshot(t))
        # current DB changes -> compare reports it, new revision appended
        self.store.add('param', 'timeout', {'value': 30}, 'model', 'r', model='34465A', session=self.session)
        o2 = pm.resolve('34465A', 'A1', run_overrides=[run], store=self.store)
        cmp = pm.compare_with_current(snap, o2)
        self.assertFalse(cmp['same'])
        self.assertEqual(cmp['added'], [('param', 'timeout')])
        snap2 = pm.build_snapshot(o2, prior=snap)
        self.assertEqual([r['rev'] for r in snap2['revs']], [1, 2])
        self.assertNotEqual(snap2['hash'], snap['hash'])
        self.assertEqual(pm.restore_snapshot(snap2, rev=1, devmode=self.dm).hash, o.hash)

    def test_record_run_snapshot_and_demo(self):
        self.add_nplc()
        o = pm.resolve('34465A', None, store=self.store)
        self.assertFalse(pm.record_run_snapshot(7, o, demo=True, store=self.store))
        self.assertIsNone(pm.get_run_snapshot(7, store=self.store))
        self.assertTrue(pm.record_run_snapshot(7, o, store=self.store))
        self.assertEqual(pm.get_run_snapshot(7, store=self.store)['hash'], o.hash)
        self.assertFalse(pm.record_run_snapshot(8, pm.resolve('x', None, store=self.store), store=self.store))      # unmodified
        con = sqlite3.connect(self.db)
        con.execute("UPDATE run_overrides SET snapshot_json='{}' WHERE run_id='7'")
        con.commit()
        con.close()
        self.assertIsNone(pm.get_run_snapshot(7, store=self.store))                                # checksum mismatch

    def test_unmodified_summary_empty(self):
        o = pm.resolve('34465A', None, store=self.store)
        self.assertEqual(pm.modifications_summary(o), [])
        self.assertEqual(o.hash, '')
        self.assertFalse(o)
        self.assertEqual(pm.apply_points(self.points, o), self.points)

    def test_summary_fields(self):
        self.add_nplc(scope='asset', asset_id='A1')
        s = pm.modifications_summary(pm.resolve('34465A', 'A1', store=self.store))
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]['unverified'])
        self.assertEqual((s[0]['author'], s[0]['reason'], s[0]['applies_to']), ('tester', 'fw 3.x', 'asset A1'))
        self.assertEqual(s[0]['date'], self.store.now().date().isoformat())


class ShareTests(Base):
    def test_export_excludes_run_and_requires_session(self):
        self.add_nplc()
        self.store.add('param', 'delay', {'value': 1.0}, 'asset', 'r', asset_id='A1', session=self.session)
        p = self.points[0]
        self.store.add('limit', pm.point_key(p), {'mode': 'error', 'error': p['error'] * 2}, 'model', 'tol', model='34465A', point=p, session=self.session)
        pm.make_run_entry('param', 'timeout', {'value': 9}, 'r', session=self.session)
        path = self.dir / 'out.calov.json'
        payload, notes = pm.export_entries(self.store, path, session=self.session)
        data = json.loads(path.read_text())
        self.assertEqual((data['format'], data['schema']), ('calov', 1))
        self.assertEqual(sorted(e['kind'] for e in data['entries']), ['command', 'limit', 'param'])
        self.assertNotIn('run', {e['scope'] for e in data['entries']})
        self.assertNotIn('mac', data['entries'][0])
        self.assertEqual(data['sha256'], pm.sha(data['entries']))
        with self.assertRaises(pm.OverrideError):
            pm.export_entries(self.store, path, session=None)

    def test_import_preview_conflicts_and_apply(self):
        e = self.add_nplc()
        p = self.points[0]
        self.store.add('limit', pm.point_key(p), {'mode': 'error', 'error': p['error'] * 2}, 'model', 'tol', model='34465A', point=p, session=self.session)
        payload, _ = pm.export_entries(self.store, session=self.session)
        # a second bench
        dm2 = devmode.DevMode(self.dir / 'b2' / 'devmode.json', clock=self.clock, wall=self.clock, iterations=1000)
        s2 = dm2.set_passphrase('second bench pw')
        st2 = pm.Store(self.dir / 'b2.sqlite3', devmode=dm2)
        prev = pm.import_preview(st2, payload, registries={'ScpiDmm': REG})
        self.assertTrue(prev['ok'])
        self.assertEqual(st2.entries(heads_only=False), [])                                        # preview applies nothing
        self.assertEqual([it['accept'] for it in prev['items']], [True, True])
        self.assertTrue(all(it['conflict'] is None for it in prev['items']))
        # unknown registry -> cannot be checked, not accepted
        self.assertEqual([it['accept'] for it in pm.import_preview(st2, payload)['items']], [False, True])
        with self.assertRaises(pm.OverrideError):
            pm.apply_import(st2, prev, session=None)
        done = pm.apply_import(st2, prev, who='bob', session=s2, accept=[0])
        self.assertEqual(len(done), 1)
        got = done[0]
        self.assertEqual(got['author'], 'tester')                                                 # original author kept
        self.assertEqual(pm.imported_by(got), 'bob')
        self.assertIsNone(got['tested'])
        self.assertEqual(len(st2.entries()), 1)
        # limit entry: signed by THIS bench's key on import, applies
        pm.apply_import(st2, prev, who='bob', session=s2, accept=[1]) if prev['items'][1]['entry']['kind'] == 'limit' else None
        o = pm.resolve('34465A', None, store=st2)
        self.assertEqual(len(o.tampered()), 0)
        self.assertTrue(o.has_limits)
        # second preview: identical conflicts, not accepted
        prev2 = pm.import_preview(st2, payload, registries={'ScpiDmm': REG})
        self.assertEqual([it['conflict'] for it in prev2['items']], ['identical', 'identical'])
        self.assertEqual([it['accept'] for it in prev2['items']], [False, False])
        # different value -> conflict 'different', can be accepted explicitly and supersedes
        payload2 = copy.deepcopy(payload)
        payload2['entries'][0]['value']['template'] = 'VOLT:DC:NPLC3 {nplc:g}'
        payload2['sha256'] = pm.sha(payload2['entries'])
        prev3 = pm.import_preview(st2, payload2, registries={'ScpiDmm': REG})
        self.assertEqual(prev3['items'][0]['conflict'], 'different')
        self.assertFalse(prev3['items'][0]['accept'])
        new = pm.apply_import(st2, prev3, who='bob', session=s2, accept=[0])[0]
        self.assertEqual((new['version'], new['supersedes'] is not None), (2, True))

    def test_import_rejections(self):
        self.add_nplc()
        payload, _ = pm.export_entries(self.store, session=self.session)
        bad = copy.deepcopy(payload)
        bad['entries'][0]['value']['template'] = 'VOLT:DC:NPLC {nplc:g};*RST'
        self.assertFalse(pm.import_preview(self.store, bad)['ok'])                                  # checksum
        bad['sha256'] = pm.sha(bad['entries'])
        item = pm.import_preview(self.store, bad, registries={'ScpiDmm': REG})['items'][0]
        self.assertFalse(item['accept'])
        self.assertTrue(item['problems'])
        for broken in ('not json', {'format': 'other'}, {'format': 'calov', 'schema': 99, 'entries': [], 'sha256': ''}):
            self.assertFalse(pm.import_preview(self.store, broken)['ok'])
        run = copy.deepcopy(payload)
        run['entries'][0]['scope'] = 'run'
        run['sha256'] = pm.sha(run['entries'])
        self.assertFalse(pm.import_preview(self.store, run, registries={'ScpiDmm': REG})['items'][0]['accept'])
        with self.assertRaises(pm.OverrideError):
            pm.apply_import(self.store, pm.import_preview(self.store, bad, registries={'ScpiDmm': REG}), session=self.session, accept=[0])


class ViewModel(Base):
    def test_rows_states_filter_search(self):
        self.store.add('command', 'D:nplc', {'template': 'VOLT:DC:NPLC2 {nplc:g}'}, 'model', 'r', model='M', cmd=NPLC, session=self.session)
        unver = Cmd('SENS:X 1', 'Unverified one', verified=False)
        regs = {'D': dict(REG, x=unver)}
        o = pm.resolve('M', None, store=self.store)
        rows = {r['key']: r for r in pm.rows(regs, o)}
        self.assertEqual({k: r['state'] for k, r in rows.items()}, {'nplc': 'modified', 'nplc?': 'factory', 'oper': 'locked', 'x': 'unverified'})
        self.assertEqual(rows['nplc']['factory'], NPLC.template)
        self.assertEqual(rows['nplc']['current'], 'VOLT:DC:NPLC2 {nplc:g}')
        self.assertTrue(rows['nplc']['unverified'] and rows['nplc']['modified'])                    # untested edit
        self.assertTrue(rows['oper']['lock_reason'])
        self.assertEqual([r['key'] for r in pm.rows(regs, o, 'modified')], ['nplc'])
        self.assertEqual(sorted(r['key'] for r in pm.rows(regs, o, 'unverified')), ['nplc', 'x'])
        self.assertEqual([r['key'] for r in pm.rows(regs, o, 'locked')], ['oper'])
        self.assertEqual([r['key'] for r in pm.rows(regs, o, 'all', 'unverified one')], ['x'])
        regs['D']['nplc'] = Cmd('VOLT:DC:NPLC {nplc:g}X', 'Set NPLC', placeholders=NPLC.placeholders, readback='nplc?')
        self.assertEqual({r['key']: r['state'] for r in pm.rows(regs, o)}['nplc'], 'stale')
        ch = pm.changes(o, driver_registries=regs)
        self.assertEqual((ch[0]['status'], ch[0]['kind']), ('stale', 'command'))

    def test_setting_rows(self):
        self.store.add('param', 'settle.ac', {'value': 8}, 'model', 'r', model='M', factory=4, session=self.session)
        rows = {r['key']: r for r in pm.setting_rows(pm.resolve('M', None, store=self.store), {'settle.ac': 4})}
        self.assertEqual((rows['settle.ac']['state'], rows['settle.ac']['current']), ('modified', 8))
        self.assertTrue(rows['settle.ac']['affects_conditions'])


class Isolation(Base):
    def test_main_db_never_opened(self):
        opened = []
        real = sqlite3.connect

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)
        sqlite3.connect = spy
        try:
            self.add_nplc()
            pm.resolve('34465A', 'A1', store=self.store)
            pm.record_run_snapshot(1, pm.resolve('34465A', None, store=self.store), store=self.store)
        finally:
            sqlite3.connect = real
        self.assertTrue(opened)
        self.assertTrue(all('calibration_procedures' not in p for p in opened), opened)
        self.assertTrue(all(p == str(self.db) for p in opened))

    def test_damaged_db_degrades(self):
        bad = self.dir / 'bad.sqlite3'
        bad.write_bytes(b'not a database' * 100)
        st = pm.Store(bad, devmode=self.dm)
        self.assertEqual(pm.resolve('M', 'A', store=st).hash, '')
        with self.assertRaises(pm.OverrideError):
            st.add('param', 'delay', {'value': 1}, 'model', 'r', model='M', session=self.session)

    def test_default_path_is_labregistry(self):
        import labregistry
        self.assertEqual(pm.Store().path, Path(labregistry.DB))


# register tunables an engine would declare (also used by the tests above)
pm.register_param('settle', 'float', 0, 120, affects_conditions=True, per_point=True, label='Settle time (s)', unit='s')
pm.register_param('settle.ac', 'float', 0, 120, affects_conditions=True, label='AC settle (s)', unit='s')
pm.register_param('delay', 'float', 0, 60, label='Delay (s)', unit='s')
pm.register_param('timeout', 'float', 0.1, 600, label='Timeout (s)', unit='s')
pm.register_param('nplc', 'float', 0.02, 100, affects_conditions=True, per_point=True, label='NPLC')


if __name__ == '__main__':
    unittest.main()
