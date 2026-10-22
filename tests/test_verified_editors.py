"""A procedure that is verified on hardware and locked is refused by EVERY editor path: the saved-changes store (devmode command / setting / point /
text / tolerance edits, import), the editor model (before a run and the in-run 'Edit procedure'), the engine, and the Datasheet Builder (save a new
version, delete, open for editing).  Running is not affected and changes saved before the lock stay as they are.  No tkinter needed.
Run:  python -m unittest tests.test_verified_editors"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import datasheet_builder as db  # noqa: E402
import datasheet_builder_ui_model as DM  # noqa: E402
import devmode  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import procmods  # noqa: E402
import procmods_engine as pe  # noqa: E402
import procmods_ui_model as M  # noqa: E402
import verified as V  # noqa: E402

procmods.register_param('settle.ac', 'float', 0, 120, affects_conditions=True, label='AC settle (s)', unit='s')
procmods.register_param('delay', 'float', 0, 60, label='Delay (s)', unit='s')
TODAY = date(2026, 10, 22)


class Base(unittest.TestCase):
    MODEL = '117'
    KEY = 'Fluke_117_Verification.py'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.db = self.t / 'lab_registry.sqlite3'
        self.dm = devmode.DevMode(self.t / 'devmode.json', iterations=1000)
        self.session = self.dm.set_passphrase('correct horse battery')
        self.store = procmods.Store(self.db, devmode=self.dm)
        self.reg = V.Registry(self.db)
        self.entry = V.Entry(self.KEY, 'Fluke 117 Performance Verification', self.MODEL, str(ROOT / 'Procedures' / self.KEY))

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, target='settle.ac', value=8, **kw):
        return self.store.add('param', target, {'value': value}, 'model', 'slower calibrator', model=self.MODEL, factory=4, session=self.session, **kw)

    def lock(self):
        return self.reg.verify(self.entry, 'Mike', '2026-10-20', today=TODAY)

    def unlock(self):
        return self.reg.unlock(self.KEY, 'Sam', 'changing a setting for a new calibrator')


class StorePaths(Base):
    def test_unlocked_is_unchanged(self):
        e = self.add()
        self.assertEqual(e['model'], '117')
        self.assertEqual(self.store.lock_reason('117'), '')

    def test_add_edit_enable_reset_and_import_are_refused_when_locked(self):
        first = self.add()
        other = self.add('delay', 3)
        self.lock()
        why = self.store.lock_reason('117')
        self.assertIn('verified on hardware', why)
        with self.assertRaises(procmods.OverrideError) as c:
            self.store.add('param', 'delay', {'value': 4}, 'asset', 'x', model='117', asset_id='A1', factory=3, session=self.session)
        self.assertIn('locked', str(c.exception))
        with self.assertRaises(procmods.OverrideError):
            self.store.edit(first['uid'], value={'value': 9}, reason='again', session=self.session)
        with self.assertRaises(procmods.OverrideError):
            self.store.set_enabled(first['uid'], False, 'Mike', self.session)
        with self.assertRaises(procmods.OverrideError):
            self.store.reset(other['uid'], 'Mike', self.session)
        payload, _ = procmods.export_entries(self.store, model='117', session=self.session)      # exporting changes nothing, so it is not refused
        preview = procmods.import_preview(self.store, payload, session=self.session)
        with self.assertRaises(procmods.OverrideError):
            procmods.apply_import(self.store, preview, session=self.session, accept=[it['index'] for it in preview['items']])

    def test_changes_saved_before_the_lock_stay_and_still_apply(self):
        self.add('settle.ac', 8)
        self.lock()
        oset = procmods.resolve('117', None, store=self.store)
        self.assertEqual(oset.param('settle.ac', 4), 8)
        self.assertEqual(len(oset.active()), 1)
        self.assertEqual(len(self.store.entries(model='117')), 1)

    def test_another_model_is_not_affected(self):
        self.lock()
        e = self.store.add('param', 'delay', {'value': 2}, 'model', 'x', model='34470A', factory=3, session=self.session)
        self.assertEqual(e['model'], '34470A')

    def test_unlock_allows_editing_again_and_lock_again_refuses(self):
        self.lock()
        self.unlock()
        e = self.add()
        self.assertTrue(e)
        with self.assertRaises(V.VerifyError):                       # something (the saved change) changed, so a plain re-lock is not allowed ...
            self.reg.relock(self.entry, 'Sam')
        self.lock()                                                   # ... verifying again locks and fingerprints the new state
        with self.assertRaises(procmods.OverrideError):
            self.store.edit(e['uid'], value={'value': 9}, reason='again', session=self.session)

    def test_the_seeded_registry_locks_the_real_store(self):
        """A Store with no explicit path uses the real registry, which is seeded: Fluke 117 is locked there."""
        with mock.patch.object(V, '_SEEDED', set()), mock.patch('labregistry.DB', self.db):
            st = procmods.Store(devmode=self.dm)
            self.assertIn('verified on hardware', st.lock_reason('117'))
            with self.assertRaises(procmods.OverrideError):
                st.add('param', 'delay', {'value': 2}, 'model', 'x', model='117', factory=3, session=self.session)
            self.assertEqual(st.lock_reason('34470A'), '')


class EditorModel(Base):
    def ctx(self, **kw):
        return M.Context(title='Fluke 117', model='117', store=self.store, **kw)

    def lock_ctl(self):
        clock = [1000.0]
        lock = M.DevLock(self.dm, clock=lambda: clock[0])
        lock.session = self.session
        return lock

    def test_model_is_read_only_with_the_plain_message_even_with_developer_mode_unlocked(self):
        lock = self.lock_ctl()
        m = M.ProcModsModel(self.ctx(), lock)
        self.assertTrue(m.editable)
        self.lock()
        m2 = M.ProcModsModel(self.ctx(), lock)
        self.assertTrue(lock.unlocked)
        self.assertFalse(m2.editable)
        self.assertIn('verified on hardware', m2.read_only_reason)
        self.assertIn('Unlock for editing', m2.read_only_reason)
        for call in (lambda: m2.stage_param('settle.ac', 9), lambda: m2.stage_skip('k', True), lambda: m2.stage_text('note:k', 'x'),
                     lambda: m2.apply(), lambda: m2.export(self.t / 'x.json')):
            with self.assertRaises(procmods.OverrideError) as c:
                call()
            self.assertIn('verified on hardware', str(c.exception))

    def test_a_model_already_open_notices_the_lock_when_it_writes(self):
        lock = self.lock_ctl()
        m = M.ProcModsModel(self.ctx(), lock)
        m.editable                                           # looked at (and cached) before the procedure was verified
        self.lock()
        with self.assertRaises(procmods.OverrideError):
            m.stage_param('settle.ac', 9)

    def test_run_scope_edit_in_the_live_editor_is_refused_too(self):
        lock = self.lock_ctl()
        bridge = mock.MagicMock()
        bridge.blocked_reason.return_value = ''
        bridge.where.return_value = {'running': True, 'current': None, 'next': None}
        bridge.locked_keys.return_value = set()
        self.lock()
        m = M.ProcModsModel(self.ctx(live=bridge, proc_key=self.KEY), lock)
        self.assertTrue(m.live_mode)
        self.assertFalse(m.editable)
        with self.assertRaises(procmods.OverrideError):
            m.stage_param('settle.ac', 9)
        self.assertEqual(m.ctx.run_entries, [])

    def test_unlocking_makes_the_model_editable_again(self):
        lock = self.lock_ctl()
        self.lock()
        self.unlock()
        m = M.ProcModsModel(self.ctx(), lock)
        self.assertTrue(m.editable, m.read_only_reason)

    def test_context_key_is_exact(self):
        lock = self.lock_ctl()
        self.lock()
        self.assertFalse(M.ProcModsModel(self.ctx(proc_key=self.KEY), lock).editable)
        self.assertTrue(M.ProcModsModel(self.ctx(proc_key='ds:other', ), lock).editable)


class EngineSide(Base):
    def app(self, **kw):
        class App(pe.ProcModsMixin):
            pass
        a = App()
        a.pm_init('handheld', self.MODEL, demo=True, store=self.store, devmode=self.dm, **kw)
        return a

    def test_mods_state_reports_the_lock_and_blocks_the_live_editor(self):
        a = self.app()
        st = a.pm_state
        self.assertEqual((st.lock_reason(), st.live_blocked_reason(), a.pm_live_blocked()), ('', '', ''))
        self.lock()
        self.assertIn('verified on hardware', st.lock_reason())
        self.assertEqual(st.live_blocked_reason(), st.lock_reason())
        self.assertEqual(a.pm_live_blocked(), st.lock_reason())

    def test_running_is_not_affected_and_saved_changes_still_apply(self):
        self.add('settle.ac', 8)
        self.lock()
        a = self.app()
        st = a.pm_state
        st.load('A1')
        self.assertEqual(a.pm_param('settle.ac', 4), 8)
        self.assertEqual(a.pm_modified_count(), 1)

    def test_proc_key_overrides_the_model(self):
        self.lock()
        a = self.app(proc_key='ds:mine')
        self.assertEqual(a.pm_state.lock_reason(), '', 'a user-built datasheet of the same model is not the verified library procedure')
        b = self.app(proc_key=self.KEY)
        self.assertTrue(b.pm_state.lock_reason())

    def test_pm_proc_key_attribute_is_read_at_init(self):
        class App(pe.ProcModsMixin):
            pm_proc_key = 'ds:abc'
        a = App()
        a.pm_init('handheld', '117', demo=True, store=self.store, devmode=self.dm)
        self.assertEqual(a.pm_state.proc_key, 'ds:abc')

    def test_dsb_app_sets_its_own_key(self):
        src = (ROOT / 'dsb_runtime.py').read_text(encoding='utf-8')
        self.assertIn("self.pm_proc_key = 'ds:' + str(self.dsb['uid'])", src)
        self.assertLess(src.index('self.pm_proc_key ='), src.index("super().__init__(root, self.dsb['model']"))


class DatasheetBuilder(Base):
    def setUp(self):
        super().setUp()
        self.root = self.t / 'user_specs'
        self.kw = dict(root=self.root, db=self.db)
        self.ds = fx.dmm_34461a_like()
        self.first = db.save(self.ds, who='mike', **self.kw)
        self.assertTrue(self.first.ok)
        self.uid = self.first.uid
        self.ds_entry = V.make_entry('Keysight 34461A - example', self.ds.model, '', ROOT, user_uid=self.uid, spec_path=self.first.spec_path)
        self.reg.verify(self.ds_entry, 'Mike', '2026-10-20', today=TODAY)

    def versions_on_disk(self):
        return sorted(p.name for p in (self.root / 'versions' / self.uid).glob('v*.datasheet.json'))

    def test_save_of_a_new_version_is_refused_and_writes_nothing(self):
        before = self.versions_on_disk()
        spec_before = Path(self.first.spec_path).read_bytes()
        self.ds.notes = 'edited'
        res = db.save(self.ds, who='mike', **self.kw)
        self.assertFalse(res.ok)
        self.assertEqual(res.status, 'locked')
        self.assertIn('verified on hardware', str(res.problems[0]))
        self.assertIn('Duplicate', str(res.problems[0]))
        self.assertEqual(self.versions_on_disk(), before)
        self.assertEqual(Path(self.first.spec_path).read_bytes(), spec_before)
        self.assertEqual(db.load(self.uid, **self.kw).version, 1)

    def test_delete_is_refused_and_it_stays_in_the_index(self):
        self.assertFalse(db.delete(self.uid, **self.kw))
        self.assertIn(self.uid, [e['uid'] for e in db.procedure_entries(**self.kw)])

    def test_duplicate_still_works_and_the_copy_is_not_locked(self):
        res = db.duplicate(self.uid, title='copy', **self.kw)
        self.assertTrue(res.ok)
        self.assertNotEqual(res.uid, self.uid)
        self.assertEqual(db.lock_reason(res.uid, self.db), '')
        copy = db.load(res.uid, **self.kw)
        copy.notes = 'changed in the copy'
        self.assertTrue(db.save(copy, **self.kw).ok)

    def test_a_brand_new_datasheet_and_an_import_are_not_affected(self):
        other = fx.acv_bands_sheet()
        self.assertTrue(db.save(other, **self.kw).ok)

    def test_unlock_then_save_works_and_the_fingerprint_flags_the_change(self):
        self.reg.unlock(self.ds_entry.proc_key, 'Sam', 'the manufacturer reissued the datasheet')
        self.ds.notes = 'edited after unlock'
        res = db.save(self.ds, who='sam', **self.kw)
        self.assertTrue(res.ok)
        self.assertEqual(res.version, 2)
        entry = V.make_entry(self.ds_entry.name, self.ds.model, '', ROOT, user_uid=self.uid, spec_path=res.spec_path)
        st = self.reg.status(entry)
        self.assertEqual((st.kind, st.changed), ('changed', True))
        self.assertTrue(any('user spec' in c for c in st.changes))

    def test_list_model_messages_and_open_refusal(self):
        store = DM.Storage(self.root, self.db, who='tester')
        lst = DM.DatasheetList(store)
        out = lst.delete(self.uid)
        self.assertFalse(out.ok)
        self.assertIn('verified on hardware', out.message)
        self.assertIsNone(lst.open(self.uid))
        self.assertTrue(lst.refused)
        self.assertIn('Unlock for editing', lst.last_error)
        self.assertEqual(store.lock_reason(self.uid), lst.last_error)
        self.reg.unlock(self.ds_entry.proc_key, 'Sam', 'need to look inside')
        self.assertIsNotNone(lst.open(self.uid))
        self.assertFalse(lst.refused)

    def test_editor_save_gives_the_plain_message(self):
        store = DM.Storage(self.root, self.db, who='tester')
        ed = DM.GridModel.open(store, self.uid)               # opened before it was locked / by a path that does not check
        self.assertIsNotNone(ed)
        ed.ds.notes = 'edited in an open editor'
        out = ed.save()
        self.assertFalse(out.ok)
        self.assertIn('verified on hardware', out.message)
        self.assertEqual(db.load(self.uid, **self.kw).version, 1)


if __name__ == '__main__':
    unittest.main()
