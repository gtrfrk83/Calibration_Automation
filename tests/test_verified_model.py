"""Verified on hardware (verified.py): the registry, the lock, the 'changed since verification' fingerprint, the seeded list.  No tkinter.
Everything uses throw-away folders.   Run:  python -m unittest tests.test_verified_model"""
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import procmods  # noqa: E402
import verified as V  # noqa: E402

procmods.register_param('settle.ac', 'float', 0, 120, affects_conditions=True, label='AC settle (s)', unit='s')      # the tunables these tests save
procmods.register_param('delay', 'float', 0, 60, label='Delay (s)', unit='s')


def fake_install(base: Path, key='Fluke_117_Verification.py'):
    """Write every file the procedure's definition lists, so a throw-away 'install' can be changed file by file."""
    for rel in V.FILES[key]['code'] + V.FILES[key]['spec']:
        f = base / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({'file': rel, 'points': [1, 2]}) if rel.endswith('.json') else f'# {rel}\nline one\nline two\n', encoding='utf-8')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.base = self.t / 'install'
        fake_install(self.base)
        self.db = self.t / 'lab_registry.sqlite3'
        self.clock = [datetime(2026, 10, 22, 9, 0, 0)]
        self.reg = V.Registry(self.db, base=self.base, now=lambda: self.clock[0])
        self.entry = V.make_entry('Fluke 117 Performance Verification', '117', 'Procedures/Fluke_117_Verification.py', self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def tick(self, minutes=5):
        from datetime import timedelta
        self.clock[0] += timedelta(minutes=minutes)

    def verify(self, **kw):
        args = dict(who='Mike', on_date='2026-10-20', note='ran clean', hardware='Instrument: 117 SN 123; Calibrator: 5522A')
        args.update(kw)
        return self.reg.verify(self.entry, args.pop('who'), args.pop('on_date'), args.pop('note'), args.pop('hardware'), today=date(2026, 10, 22))


class Keys(unittest.TestCase):
    def test_keys_are_the_script_name_or_ds_uid(self):
        self.assertEqual(V.key_for('Procedures/Fluke_117_Verification.py', ROOT), 'Fluke_117_Verification.py')
        self.assertEqual(V.key_for(str(ROOT / 'Procedures' / 'WaveSurfer_WS4104HD.py'), ROOT), 'WaveSurfer_WS4104HD.py')
        self.assertEqual(V.key_for('x', ROOT, user_uid='Acme_DM1'), 'ds:Acme_DM1')
        self.assertTrue(V.make_entry('n', 'm', '', ROOT, user_uid='u', spec_path='/s.json').is_user_built)

    def test_every_launcher_has_a_definition_and_every_listed_file_exists(self):
        launchers = {p.name for p in (ROOT / 'Procedures').glob('*.py')} - {'User_Datasheet.py', '__init__.py'}
        self.assertEqual(launchers, set(V.FILES), 'a launcher in Procedures/ without a FILES entry (or the other way round)')
        missing = [(k, rel) for k, f in V.FILES.items() for rel in f['code'] + f['spec'] if not (ROOT / rel).is_file()]
        self.assertEqual(missing, [])
        self.assertTrue(all((ROOT / rel).is_file() for rel in V.USER_CODE))

    def test_seed_names_and_models_match_the_manager_index(self):
        src = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        for s in V.SEED:
            self.assertIn(f"('{s['name']}'", src, s['name'])
            m = re.search(r"\('" + re.escape(s['name']) + r"','[^']*','([^']*)'", src)
            self.assertEqual(m.group(1), s['model'])
            self.assertIn(f"'{s['name']}': '{s['proc_key']}'", src)
            self.assertTrue((ROOT / 'Procedures' / s['proc_key']).is_file())
        self.assertEqual([s['proc_key'] for s in V.SEED],
                         ['Tektronix_TDS2000C_Verification.py', 'WaveSurfer_WS4104HD.py', 'Fluke_117_Verification.py'])


class Forms(unittest.TestCase):
    TODAY = date(2026, 10, 22)

    def test_verify_form(self):
        clean, bad = V.check_verify_form(' Mike ', '', ' note ', '', self.TODAY)
        self.assertEqual((bad, clean['who'], clean['on_date'], clean['note']), ([], 'Mike', '2026-10-22', 'note'))     # blank date = today
        self.assertEqual(V.check_verify_form('Mike', '10/20/2026', '', '', self.TODAY)[0]['on_date'], '2026-10-20')
        self.assertTrue(V.check_verify_form('', '', '', '', self.TODAY)[1])                                          # who is required
        self.assertIn('future', ' '.join(V.check_verify_form('Mike', '2026-12-01', '', '', self.TODAY)[1]))
        self.assertIn('not understood', ' '.join(V.check_verify_form('Mike', 'last tuesday', '', '', self.TODAY)[1]))
        self.assertTrue(V.check_verify_form('M' * 81, '', '', '', self.TODAY)[1])

    def test_unlock_form_needs_a_typed_reason(self):
        self.assertTrue(V.check_unlock_form('Mike', '')[1])
        self.assertTrue(V.check_unlock_form('Mike', 'fix')[1])
        self.assertTrue(V.check_unlock_form('', 'new calibrator model')[1])
        clean, bad = V.check_unlock_form(' Mike ', ' new calibrator model ')
        self.assertEqual((bad, clean), ([], {'who': 'Mike', 'reason': 'new calibrator model'}))

    def test_hardware_line(self):
        self.assertEqual(V.compose_hardware('117 SN 5', '5522A'), 'Instrument: 117 SN 5; Calibrator: 5522A')
        self.assertEqual(V.compose_hardware('', ' '), '')


class Lifecycle(Base):
    def test_not_verified_is_editable(self):
        self.assertEqual(self.reg.status(self.entry).kind, 'none')
        self.assertEqual(self.reg.lock_reason(proc_key=self.entry.proc_key, model='117'), '')
        self.assertEqual(self.reg.status(self.entry).text, 'Not verified')

    def test_verify_locks_and_records_who_when_what(self):
        rec = self.verify()
        self.assertTrue(rec.locked)
        self.assertEqual((rec.verified_by, rec.verified_on, rec.source), ('Mike', '2026-10-20', 'user'))
        self.assertIn('117 SN 123', rec.hardware)
        st = self.reg.status(self.entry)
        self.assertEqual((st.kind, st.changed, st.text), ('verified', False, 'Verified 2026-10-20  [locked]'))
        why = self.reg.lock_reason(proc_key=self.entry.proc_key)
        self.assertIn('verified on hardware', why)
        self.assertIn('Unlock for editing', why)
        self.assertIn('Running it is not affected', why)
        self.assertIn('stay as they are', why)

    def test_cannot_verify_twice_while_locked_and_unchanged(self):
        self.verify()
        with self.assertRaises(V.VerifyError) as c:
            self.verify()
        self.assertIn('unlock', str(c.exception))

    def test_bad_form_raises_and_writes_nothing(self):
        with self.assertRaises(V.VerifyError):
            self.verify(who='')
        with self.assertRaises(V.VerifyError):
            self.verify(on_date='2027-01-01')
        self.assertEqual(self.reg.records(), {})

    def test_unlock_needs_a_reason_and_is_recorded(self):
        self.verify()
        self.tick()
        with self.assertRaises(V.VerifyError):
            self.reg.unlock(self.entry.proc_key, 'Sam', '')
        self.assertTrue(self.reg.record(self.entry.proc_key).locked)
        rec = self.reg.unlock(self.entry.proc_key, 'Sam', 'new calibrator firmware needs a settle change')
        self.assertFalse(rec.locked)
        self.assertEqual((rec.unlocked_by, rec.unlock_reason), ('Sam', 'new calibrator firmware needs a settle change'))
        self.assertTrue(rec.unlocked_at.startswith('2026-10-22T09:05'))
        self.assertEqual(self.reg.lock_reason(proc_key=self.entry.proc_key), '')
        self.assertEqual(self.reg.status(self.entry).kind, 'unlocked')
        self.assertEqual([h['action'] for h in self.reg.history(self.entry.proc_key)], ['verify', 'unlock'])
        self.assertEqual(self.reg.history(self.entry.proc_key)[1]['reason'], 'new calibrator firmware needs a settle change')

    def test_unlock_of_an_unverified_or_unlocked_procedure_is_refused(self):
        with self.assertRaises(V.VerifyError):
            self.reg.unlock(self.entry.proc_key, 'Sam', 'no reason needed here')
        self.verify()
        self.reg.unlock(self.entry.proc_key, 'Sam', 'looking at the settle times')
        with self.assertRaises(V.VerifyError):
            self.reg.unlock(self.entry.proc_key, 'Sam', 'looking at the settle times')

    def test_relock_only_when_nothing_changed(self):
        self.verify()
        self.reg.unlock(self.entry.proc_key, 'Sam', 'just had a look at the commands')
        st = self.reg.status(self.entry)
        self.assertEqual((st.kind, st.changed), ('unlocked', False))
        self.assertEqual(V.ui_state(st)['lock'], ('Lock again (nothing changed)', True))
        rec = self.reg.relock(self.entry, 'Sam')
        self.assertTrue(rec.locked)
        self.assertEqual(self.reg.status(self.entry).kind, 'verified')
        self.reg.unlock(self.entry.proc_key, 'Sam', 'now changing the engine')
        (self.base / 'handheld_dmm.py').write_text('# edited\n', encoding='utf-8')
        st = self.reg.status(self.entry)
        self.assertEqual((st.kind, st.changed), ('changed', True))
        self.assertEqual(V.ui_state(st)['lock'][1], False)
        with self.assertRaises(V.VerifyError) as c:
            self.reg.relock(self.entry, 'Sam')
        self.assertIn('verified again', str(c.exception))
        self.verify(on_date='2026-10-22')                           # verifying again locks it and takes a new fingerprint
        self.assertEqual(self.reg.status(self.entry).kind, 'verified')

    def test_events_are_append_only(self):
        self.verify()
        con = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("UPDATE proc_verify_events SET who='x'")
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute('DELETE FROM proc_verify_events')
        with self.assertRaises(sqlite3.DatabaseError):                        # the table itself refuses an unlock without a reason
            con.execute("INSERT INTO proc_verify_events(proc_key,action,at,who,reason) VALUES('k','unlock','t','w','')")
        con.close()

    def test_no_existing_table_is_touched(self):
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY, asset_id TEXT)')
        con.execute("INSERT INTO runs(asset_id) VALUES('A1')")
        con.commit()
        con.close()
        self.verify()
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute('SELECT asset_id FROM runs').fetchall(), [('A1',)])
        self.assertEqual({r[0] for r in con.execute("select name from sqlite_master where type='table'")} - {'sqlite_sequence'}, {'runs', 'proc_verify_events'})
        con.close()


class ChangedSince(Base):
    def test_a_replaced_file_unlocks_it_once_and_it_needs_reverification(self):
        for rel, text in (('handheld_dmm.py', '# new engine\n'), ('specs/fluke_110_series_pv.json', '{"new": true}'), ('drivers/fluke_5560a.py', '# drv\n'),
                          ('Procedures/Fluke_117_Verification.py', '# launcher\n')):
            with self.subTest(rel):
                self.verify(on_date='2026-10-21')                         # (re)verified: locked again, fingerprint of the files as they are now
                self.assertTrue(self.reg.lock_reason(proc_key=self.entry.proc_key))
                path = self.base / rel
                before = path.read_text(encoding='utf-8')
                n_before = len(self.reg.history(self.entry.proc_key))
                path.write_text(text, encoding='utf-8')
                for _ in range(3):                                         # looked at again and again: still ONE event
                    st = self.reg.status(self.entry)
                self.assertEqual((st.kind, st.changed, st.locked), ('changed', True, False))
                self.assertEqual(st.text, 'Changed since verification - needs hardware re-verification')
                self.assertTrue(any(rel in c for c in st.changes), st.changes)
                self.assertEqual(self.reg.lock_reason(proc_key=self.entry.proc_key), '', 'not locked: editable')
                self.assertEqual(self.reg.lock_reason(model='117'), '')
                hist = self.reg.history(self.entry.proc_key)
                self.assertEqual(len(hist), n_before + 1)
                self.assertEqual((hist[-1]['action'], hist[-1]['who']), ('unlock', 'system'))
                self.assertTrue(hist[-1]['reason'].startswith('files changed since verification: '))
                self.assertIn(rel, hist[-1]['reason'])
                self.assertEqual(V.ui_state(st)['verify'], ('Mark verified on hardware...', True))
                self.assertEqual(V.ui_state(st)['lock'][1], False)
                path.write_text(before, encoding='utf-8')                  # putting the file back: unchanged again, but still unlocked
                self.assertEqual(self.reg.status(self.entry).kind, 'unlocked')

    def test_an_editor_asking_whether_it_is_locked_triggers_the_auto_unlock(self):
        self.verify()
        self.assertTrue(self.reg.lock_reason(model='117'))
        (self.base / 'handheld_dmm.py').write_text('# updated\n', encoding='utf-8')
        self.assertEqual(self.reg.lock_reason(model='117'), '')
        h = self.reg.history(self.entry.proc_key)
        self.assertEqual([(e['action'], e['who']) for e in h], [('verify', 'Mike'), ('unlock', 'system')])
        self.assertEqual(self.reg.lock_reason(proc_key=self.entry.proc_key), '')
        self.assertEqual(len(self.reg.history(self.entry.proc_key)), 2)

    def test_marking_verified_again_locks_the_new_version(self):
        self.verify()
        (self.base / 'handheld_dmm.py').write_text('# updated\n', encoding='utf-8')
        self.assertEqual(self.reg.status(self.entry).kind, 'changed')
        self.verify(on_date='2026-10-22')
        st = self.reg.status(self.entry)
        self.assertEqual((st.kind, st.changed), ('verified', False))
        self.assertTrue(self.reg.lock_reason(proc_key=self.entry.proc_key))

    def test_unchanged_procedures_are_never_auto_unlocked(self):
        self.verify()
        for _ in range(3):
            self.reg.status(self.entry)
            self.reg.lock_reason(model='117')
        self.assertEqual([e['action'] for e in self.reg.history(self.entry.proc_key)], ['verify'])

    def test_line_endings_and_json_layout_do_not_count_as_a_change(self):
        self.verify()
        py = self.base / 'handheld_dmm.py'
        py.write_bytes(py.read_bytes().replace(b'\n', b'\r\n'))
        js = self.base / 'specs' / 'fluke_110_series_pv.json'
        js.write_text(json.dumps(json.loads(js.read_text(encoding='utf-8')), indent=4, sort_keys=False), encoding='utf-8')
        self.assertEqual(self.reg.status(self.entry).kind, 'verified')

    def test_a_removed_file_is_a_change(self):
        self.verify()
        (self.base / 'hookups.py').unlink()
        st = self.reg.status(self.entry)
        self.assertEqual(st.kind, 'changed')
        self.assertTrue(any('hookups.py' in c for c in st.changes))

    def test_saved_procedure_changes_are_part_of_the_definition(self):
        import devmode
        dm = devmode.DevMode(self.t / 'dev.json', iterations=1000)
        session = dm.set_passphrase('correct horse battery')
        store = procmods.Store(self.db, devmode=dm)
        store.add('param', 'settle.ac', {'value': 6}, 'model', 'slower calibrator', model='117', factory=4, session=session)
        self.verify()                                   # the saved change is part of what was verified
        self.assertEqual(self.reg.status(self.entry).kind, 'verified')
        self.reg.unlock(self.entry.proc_key, 'Sam', 'changing the settle again')
        store.add('param', 'delay', {'value': 5}, 'model', 'another one', model='117', factory=3, session=session)
        st = self.reg.status(self.entry)
        self.assertEqual((st.kind, st.changed), ('changed', True))
        self.assertTrue(any('delay' in c for c in st.changes), st.changes)

    def test_detail_lines_say_what_is_going_on(self):
        self.verify()
        text = ' '.join(self.reg.status(self.entry).detail_lines())
        self.assertIn('Mike', text)
        self.assertIn('2026-10-20', text)
        self.assertIn('117 SN 123', text)
        (self.base / 'handheld_dmm.py').write_text('# new\n', encoding='utf-8')
        self.assertIn('handheld_dmm.py', ' '.join(self.reg.status(self.entry).detail_lines()))

    def test_user_built_fingerprint_is_its_spec_file(self):
        spec = self.t / 'u.json'
        spec.write_text('{"a": 1}', encoding='utf-8')
        (self.base / 'dsb_runtime.py').write_text('# rt\n', encoding='utf-8')
        (self.base / 'Procedures').mkdir(exist_ok=True)
        (self.base / 'Procedures' / 'User_Datasheet.py').write_text('# l\n', encoding='utf-8')
        e = V.make_entry('Acme DM1', 'DM-1', '', self.base, user_uid='Acme_DM1', spec_path=str(spec))
        self.reg.verify(e, 'Mike', '2026-10-20', today=date(2026, 10, 22))
        self.assertEqual(self.reg.status(e).kind, 'verified')
        spec.write_text('{"a": 2}', encoding='utf-8')
        st = self.reg.status(e)
        self.assertEqual(st.kind, 'changed')
        self.assertTrue(any('user spec' in c for c in st.changes))


class LockMatching(Base):
    def test_by_model_matches_library_procedures_only(self):
        self.verify()
        self.assertTrue(self.reg.lock_reason(model='117'))
        self.assertTrue(self.reg.lock_reason(model=' 117 '))
        self.assertEqual(self.reg.lock_reason(model='34470A'), '')
        self.assertEqual(self.reg.lock_reason(model=''), '')
        spec = self.t / 'u.json'
        spec.write_text('{}', encoding='utf-8')
        e = V.make_entry('Mine', 'M-9', '', self.base, user_uid='Mine', spec_path=str(spec))
        self.reg.verify(e, 'Mike', '2026-10-20', today=date(2026, 10, 22))
        self.assertTrue(self.reg.lock_reason(proc_key='ds:Mine'))
        self.assertEqual(self.reg.lock_reason(model='M-9'), '', 'a user-built lock is by key, it must not lock a library model of the same name')
        self.assertEqual(self.reg.lock_reason(proc_key='ds:Other', model='117'), '', 'a given key is matched exactly')

    def test_ds_lock_text_offers_duplicate(self):
        spec = self.t / 'u.json'
        spec.write_text('{}', encoding='utf-8')
        e = V.make_entry('Mine', 'M-9', '', self.base, user_uid='Mine', spec_path=str(spec))
        self.reg.verify(e, 'Mike', '2026-10-20', today=date(2026, 10, 22))
        self.assertIn('Duplicate', self.reg.lock_reason(proc_key='ds:Mine'))

    def test_a_lock_check_creates_nothing(self):
        fresh = V.Registry(self.t / 'nothing.sqlite3', base=self.base)
        self.assertEqual(fresh.lock_reason(model='117'), '')
        self.assertFalse((self.t / 'nothing.sqlite3').exists())
        empty = self.t / 'empty.sqlite3'
        sqlite3.connect(empty).close()
        self.assertEqual(V.Registry(empty).lock_reason(model='117'), '')
        con = sqlite3.connect(empty)
        self.assertEqual(con.execute("select count(*) from sqlite_master").fetchone()[0], 0)
        con.close()


class Seeded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'lab_registry.sqlite3'
        V._SEEDED.discard(str(self.db))

    def tearDown(self):
        V._SEEDED.discard(str(self.db))
        self.tmp.cleanup()

    def test_the_three_are_seeded_verified_and_locked(self):
        reg = V.Registry(self.db, seed=True)
        recs = reg.records()
        self.assertEqual(set(recs), {'tektronix_tds2000c_verification.py', 'wavesurfer_ws4104hd.py', 'fluke_117_verification.py'})
        for r in recs.values():
            self.assertTrue(r.locked)
            self.assertEqual((r.source, r.verified_by, r.verified_on), ('seed', V.SEED_WHO, V.SEED_DATE))
            self.assertTrue(r.hash)
        for model in ('TDS2000C/TDS1000C-EDU', 'WS4104HD', '117'):
            self.assertTrue(reg.lock_reason(model=model), model)
        for model in ('34470A', '87V', '8846A', 'MDO4000C', '33220A'):
            self.assertEqual(reg.lock_reason(model=model), '', model)
        for s in V.SEED:
            e = V.make_entry(s['name'], s['model'], 'Procedures/' + s['proc_key'])
            st = reg.status(e)
            self.assertEqual((st.kind, st.changed), ('verified', False), s['proc_key'])
            self.assertIn('lab owner', ' '.join(st.detail_lines()))

    def test_seeding_is_once_and_never_relocks_an_unlock(self):
        reg = V.Registry(self.db, seed=True)
        self.assertEqual(len(reg.records()), 3)
        reg.unlock('Fluke_117_Verification.py', 'Mike', 'adding a new calibrator type')
        V._SEEDED.discard(str(self.db))                                     # a new process
        again = V.Registry(self.db, seed=True)
        self.assertFalse(again.records()['fluke_117_verification.py'].locked)
        self.assertEqual(again.ensure_seeded(), 0)
        self.assertEqual(len(again.history('Fluke_117_Verification.py')), 2)

    def test_an_explicit_path_is_not_seeded(self):
        reg = V.Registry(self.db)
        self.assertEqual(reg.records(), {})
        self.assertEqual(reg.lock_reason(model='117'), '')
        self.assertFalse(self.db.exists())

    def test_default_registry_is_the_real_one_and_is_seeded(self):
        import labregistry
        self.assertTrue(V.Registry().seed)
        self.assertEqual(V.Registry().path, Path(labregistry.DB))

    def test_unreadable_registry_keeps_the_seeded_procedures_locked(self):
        self.db.write_bytes(b'not a database' * 50)
        bad = V.Registry(self.db, seed=True)
        self.assertTrue(bad.lock_reason(model='117'))
        self.assertTrue(bad.lock_reason(proc_key='WaveSurfer_WS4104HD.py'))
        self.assertEqual(bad.lock_reason(model='34470A'), '')
        st = bad.status(V.make_entry('x', '117', 'Procedures/Fluke_117_Verification.py'))
        self.assertEqual(st.kind, 'verified')
        # an unseeded registry that cannot be read does not lock anything (nothing was ever marked)
        self.assertEqual(V.Registry(self.db).lock_reason(model='117'), '')


class Buttons(unittest.TestCase):
    def test_button_table(self):
        rec = V.Record('k', 'n', 'm', verified_on='2026-10-20', verified_by='Mike')
        cases = {
            ('none', False): (('Mark verified on hardware...', True), ('Unlock for editing...', False)),
            ('verified', False): (('Mark verified on hardware...', False), ('Unlock for editing...', True)),
            ('changed', True): (('Mark verified on hardware...', True), ('Lock again (nothing changed)', False)),
            ('unlocked', False): (('Mark verified again...', True), ('Lock again (nothing changed)', True)),
            ('unlocked', True): (('Mark verified again...', True), ('Lock again (nothing changed)', False)),
        }
        for (kind, changed), (verify, lock) in cases.items():
            st = V.Status(kind, rec if kind != 'none' else None, [], changed)
            got = V.ui_state(st)
            self.assertEqual((got['verify'], got['lock']), (verify, lock), (kind, changed))

    def test_cells_and_pills(self):
        rec = V.Record('k', 'n', 'm', verified_on='2026-10-20', verified_by='Mike')
        self.assertEqual(V.Status('verified', rec).text, 'Verified 2026-10-20  [locked]')
        self.assertEqual(V.Status('changed', rec, ['x'], True).text, 'Changed since verification - needs hardware re-verification')
        self.assertEqual(V.Status('unlocked', rec).text, 'Verified 2026-10-20  [UNLOCKED]')
        self.assertEqual(V.Status('unlocked', rec, ['x'], True).text, 'Verified 2026-10-20  [UNLOCKED]  changed')
        self.assertEqual(V.Status('none').text, 'Not verified')
        self.assertIn('LOCKED', V.Status('verified', rec).pill)
        self.assertEqual(V.Status('changed', rec, ['x'], True).pill, 'CHANGED SINCE VERIFICATION - NEEDS HARDWARE RE-VERIFICATION')
        self.assertEqual(V.Status('changed', rec, ['x'], True).tone, 'warn')
        self.assertEqual(V.Status('verified', rec).tone, 'good')


if __name__ == '__main__':
    unittest.main()
