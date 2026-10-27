"""Datasheet Builder storage: versions, registry (lab_registry.sqlite3 only), duplicate / soft delete / export / import, damaged-file safety.
Everything uses throw-away folders.   Run:  python -m unittest tests.test_datasheet_builder_store"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import datasheet_builder as db  # noqa: E402
import dsb_fixtures as fx  # noqa: E402


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'user_specs'
        self.db = Path(self.tmp.name) / 'lab_registry.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def kw(self):
        return dict(root=self.root, db=self.db)

    def test_first_save_writes_version_runnable_spec_and_registry_row(self):
        ds = fx.dmm_34461a_like()
        r = db.save(ds, who='mike', note='first', **self.kw())
        self.assertTrue(r.ok)
        self.assertEqual((r.version, r.status, r.uid), (1, 'ready', 'Keysight_34461A_34461A-example-datasheet'))
        self.assertEqual(Path(r.spec_path), self.root / f'{r.uid}.json')
        self.assertTrue((self.root / 'versions' / r.uid / 'v0001.datasheet.json').is_file())
        self.assertTrue((self.root / 'versions' / r.uid / 'v0001.spec.json').is_file())
        spec = json.loads(Path(r.spec_path).read_text(encoding='utf-8'))
        self.assertEqual(spec['dsb']['version'], 1)
        rows = db.list_datasheets(**self.kw())
        self.assertEqual([(x['uid'], x['version'], x['status'], x['tag']) for x in rows], [(r.uid, 1, 'ready', 'user-built')])
        self.assertEqual(ds.version, 1)

    def test_every_save_is_a_new_version_and_old_ones_stay_byte_identical(self):
        ds = fx.dmm_34461a_like()
        r1 = db.save(ds, **self.kw())
        first = (self.root / 'versions' / r1.uid / 'v0001.datasheet.json').read_bytes()
        ds.notes = 'changed'
        r2 = db.save(ds, who='x', note='second', **self.kw())
        r3 = db.save(ds, **self.kw())
        self.assertEqual((r2.version, r3.version, r2.uid), (2, 3, r1.uid))
        self.assertEqual((self.root / 'versions' / r1.uid / 'v0001.datasheet.json').read_bytes(), first)
        vs = db.versions(r1.uid, **self.kw())
        self.assertEqual([v['version'] for v in vs], [3, 2, 1])
        self.assertEqual(vs[1]['who'], 'x')
        self.assertEqual(db.load(r1.uid, 1, **self.kw()).notes, '')
        self.assertEqual(db.load(r1.uid, 2, **self.kw()).notes, 'changed')
        self.assertEqual(db.load(r1.uid, **self.kw()).version, 3)

    def test_a_second_datasheet_with_the_same_name_never_takes_over_the_first(self):
        a = db.save(fx.dmm_34461a_like(), **self.kw())
        b = db.save(fx.dmm_34461a_like(), **self.kw())                  # a new Datasheet object with the same make / model / title
        self.assertNotEqual(a.uid, b.uid)
        self.assertEqual(b.version, 1)
        self.assertEqual(len(db.list_datasheets(**self.kw())), 2)

    def test_a_datasheet_with_errors_is_saved_as_a_draft_and_the_runnable_spec_is_kept(self):
        ds = fx.dmm_34461a_like()
        good = db.save(ds, **self.kw())
        runnable = Path(good.spec_path).read_bytes()
        ds.function('dcv').ranges[0].resolution = db.D(-1)
        bad = db.save(ds, **self.kw())
        self.assertTrue(bad.ok)
        self.assertEqual((bad.status, bad.version, bad.spec_path), ('draft', 2, ''))
        self.assertIn('range_resolution', [p.code for p in bad.problems])
        self.assertEqual(Path(good.spec_path).read_bytes(), runnable)            # the runnable file is untouched
        row = db.list_datasheets(**self.kw())[0]
        self.assertEqual((row['version'], row['runnable_version'], row['status']), (2, 1, 'draft'))
        self.assertEqual(db.load(good.uid, **self.kw()).function('dcv').ranges[0].resolution, db.D(-1))     # the draft itself is kept

    def test_procedure_entries_are_the_user_built_rows(self):
        r = db.save(fx.dmm_34461a_like(), **self.kw())
        rows = db.procedure_entries(**self.kw())
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['tag'], rows[0]['category'], rows[0]['manufacturer'], rows[0]['model'], rows[0]['spec_path']),
                         ('user-built', 'User-built', 'Keysight', '34461A', r.spec_path))
        draft = fx.dmm_34461a_like()
        draft.title = 'Draft only'
        draft.function('dcv').ranges[0].resolution = db.D(-1)
        db.save(draft, **self.kw())
        self.assertEqual(len(db.procedure_entries(**self.kw())), 1)              # a draft has no runnable spec: not a procedure

    def test_duplicate(self):
        r = db.save(fx.dmm_34461a_like(), **self.kw())
        d = db.duplicate(r.uid, title='34461A copy', **self.kw())
        self.assertTrue(d.ok and d.uid != r.uid and d.version == 1)
        self.assertEqual(db.load(d.uid, **self.kw()).title, '34461A copy')
        self.assertEqual(db.load(r.uid, **self.kw()).title, '34461A example datasheet')
        self.assertIsNone(db.duplicate('nope', **self.kw()))

    def test_soft_delete_and_restore(self):
        r = db.save(fx.dmm_34461a_like(), **self.kw())
        self.assertTrue(db.delete(r.uid, **self.kw()))
        self.assertEqual(db.list_datasheets(**self.kw()), [])
        self.assertEqual(len(db.list_datasheets(include_deleted=True, **self.kw())), 1)
        self.assertEqual(db.procedure_entries(**self.kw()), [])
        self.assertFalse(Path(r.spec_path).exists())
        self.assertTrue((self.root / 'versions' / r.uid / 'v0001.datasheet.json').is_file())      # every version file stays
        self.assertIsNotNone(db.load(r.uid, **self.kw()))
        self.assertFalse(db.delete(r.uid, **self.kw()))
        self.assertTrue(db.restore(r.uid, **self.kw()))
        self.assertEqual(len(db.procedure_entries(**self.kw())), 1)
        self.assertTrue(Path(r.spec_path).is_file())

    def test_export_and_import_json(self):
        r = db.save(fx.generator_33220a_like(), **self.kw())
        out = Path(self.tmp.name) / 'out.json'
        self.assertTrue(db.export_json(r.uid, out, **self.kw()))
        imp = db.import_json(out, who='me', **self.kw())
        self.assertTrue(imp.ok)
        self.assertNotEqual(imp.uid, r.uid)                                       # never overwrites
        self.assertEqual(db.load(imp.uid, **self.kw()).to_dict()['functions'], db.load(r.uid, **self.kw()).to_dict()['functions'])
        # a runnable spec (which embeds the datasheet) imports too
        imp2 = db.import_json(r.spec_path, **self.kw())
        self.assertTrue(imp2.ok and imp2.uid not in (r.uid, imp.uid))
        self.assertFalse(db.export_json('nope', out, **self.kw()))

    def test_import_of_junk_stores_nothing(self):
        before = db.list_datasheets(**self.kw())
        for text in ('not json', '{"schema": "other"}', '[]', '{"schema": "dsb-1", "functions": [{"id": "x"}]}'):
            f = Path(self.tmp.name) / 'junk.json'
            f.write_text(text, encoding='utf-8')
            res = db.import_json(f, **self.kw())
            self.assertFalse(res.ok, text)
            self.assertTrue(res.problems)
        self.assertFalse(db.import_json(Path(self.tmp.name) / 'missing.json', **self.kw()).ok)
        self.assertEqual(db.list_datasheets(**self.kw()), before)
        self.assertFalse((self.root / 'versions').exists() and list((self.root / 'versions').iterdir()))

    def test_registry_tables_are_new_and_the_manager_database_is_not_touched(self):
        db.save(fx.dmm_34461a_like(), **self.kw())
        con = sqlite3.connect(self.db)
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertTrue({'user_datasheets', 'user_datasheet_versions'} <= names)
        self.assertFalse(any('calibration_procedures' in n for n in names))
        self.assertFalse((Path(self.tmp.name) / 'calibration_procedures.sqlite3').exists())

    def test_existing_registry_tables_survive(self):
        import specmanager as sm
        sm.seed(path=self.db)
        n = len(sm.standards(self.db))
        db.save(fx.dmm_34461a_like(), **self.kw())
        self.assertEqual(len(sm.standards(self.db)), n)


class DamagedFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'user_specs'
        self.db = Path(self.tmp.name) / 'lab_registry.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def kw(self):
        return dict(root=self.root, db=self.db)

    def test_damaged_registry_never_raises_and_files_still_save_and_load(self):
        r = db.save(fx.dmm_34461a_like(), **self.kw())
        self.db.write_bytes(b'this is not a database' * 50)
        self.assertEqual(len(db.list_datasheets(**self.kw())), 1)                  # falls back to the files
        self.assertEqual(len(db.procedure_entries(**self.kw())), 1)                  # the runnable spec file is still offered as a procedure
        self.assertEqual(db.load(r.uid, **self.kw()).version, 1)
        self.assertEqual([v['version'] for v in db.versions(r.uid, **self.kw())], [1])
        ds = db.load(r.uid, **self.kw())
        r2 = db.save(ds, **self.kw())
        self.assertTrue(r2.ok)
        self.assertEqual(r2.version, 2)                                              # the version number comes from the files
        self.assertIn('registry', [p.code for p in r2.problems])
        self.assertFalse(db.delete(r.uid, **self.kw()))
        self.assertFalse(db.restore(r.uid, **self.kw()))

    def test_missing_registry_and_directory_as_database(self):
        self.assertEqual(db.list_datasheets(**self.kw()), [])
        self.assertIsNone(db.load('nope', **self.kw()))
        self.assertEqual(db.versions('nope', **self.kw()), [])
        d = Path(self.tmp.name) / 'dir.sqlite3'
        d.mkdir()
        self.assertEqual(db.list_datasheets(root=self.root, db=d), [])
        self.assertIsNone(db.load('nope', root=self.root, db=d))

    def test_damaged_datasheet_file_loads_as_none(self):
        r = db.save(fx.dmm_34461a_like(), **self.kw())
        f = self.root / 'versions' / r.uid / 'v0001.datasheet.json'
        f.write_text('{"schema": "dsb-1", "functions": ', encoding='utf-8')
        self.assertIsNone(db.load(r.uid, **self.kw()))
        self.assertIsNone(db.load(r.uid, 1, **self.kw()))
        self.assertEqual(len(db.list_datasheets(**self.kw())), 1)

    def test_unwritable_folder_returns_a_problem_not_an_exception(self):
        blocker = Path(self.tmp.name) / 'afile'
        blocker.write_text('x')
        r = db.save(fx.dmm_34461a_like(), root=blocker / 'sub', db=self.db)
        self.assertFalse(r.ok)
        self.assertIn('write', [p.code for p in r.problems])

    def test_user_specs_dir_lives_in_the_app_data_folder(self):
        import appdata
        old = os.environ.get('CALSUITE_DATA')
        os.environ['CALSUITE_DATA'] = self.tmp.name
        try:
            self.assertEqual(db.user_specs_dir(), Path(self.tmp.name) / 'user_specs')
            self.assertEqual(appdata.data_dir(), Path(self.tmp.name))
        finally:
            if old is None:
                os.environ.pop('CALSUITE_DATA')
            else:
                os.environ['CALSUITE_DATA'] = old

    def test_file_names_are_make_model_slug(self):
        ds = db.Datasheet('Fluke / Co', '87 V', 'Cal: 2024 rev #2')
        self.assertEqual(db.make_uid(ds), 'Fluke-Co_87-V_Cal-2024-rev-2')


if __name__ == '__main__':
    unittest.main()


class ManagerRemoveUser(unittest.TestCase):
    """Manual Calibrations rows are user-built procedures: the Manager's right-click 'Remove from library' soft-deletes them (it used to only show a message)."""

    def test_remove_user_is_a_soft_delete_and_can_be_restored(self):
        import types
        import manager_model as mm
        with tempfile.TemporaryDirectory() as tmp:
            root, reg = Path(tmp) / 'user_specs', Path(tmp) / 'lab_registry.sqlite3'
            r = db.save(fx.dmm_34461a_like(), root=root, db=reg)
            core = types.SimpleNamespace(user={'ds:' + r.uid: dict(uid=r.uid, name='Example')})
            ok, text = mm.ManagerCore.remove_user(core, 'ds:' + r.uid, root=root, db=reg)
            self.assertTrue(ok, text)
            self.assertEqual(db.list_datasheets(root=root, db=reg), [])
            self.assertFalse(mm.ManagerCore.remove_user(core, 'ds:' + r.uid, root=root, db=reg)[0])      # already gone
            self.assertTrue(db.restore(r.uid, root=root, db=reg))
            self.assertFalse(mm.ManagerCore.remove_user(core, 'ds:unknown', root=root, db=reg)[0])


class ManagerExportPackage(unittest.TestCase):
    """The Manager's 'Export procedure package...' (Library menu and the row's right-click menu) writes the same zip tools/make_package.py does."""

    def test_export_writes_an_inspectable_package_and_refuses_a_user_built_row(self):
        import types
        import manager_model as mm
        import packages
        import verified
        root = HERE.parent
        with tempfile.TemporaryDirectory() as tmp:
            core = types.SimpleNamespace(user={}, base=root)
            core.verified = lambda: verified.Registry(Path(tmp) / 'lab_registry.sqlite3', base=root, seed=False)
            core.exportable = lambda rec: mm.ManagerCore.exportable(core, rec)
            rec = ('1', 'Fluke 753 Verification', 'Fluke', '753', 'x', 'Procedures/Fluke_753_Verification.py', '')
            self.assertTrue(mm.ManagerCore.exportable(core, rec))
            path, digest = mm.ManagerCore.export_package(core, rec, tmp)
            self.assertTrue(Path(path).is_file() and len(digest) == 64)
            pv = packages.inspect(path, root, core.verified(), None)
            self.assertEqual(pv.errors, [] if hasattr(pv, 'errors') else [])
            self.assertFalse(mm.ManagerCore.exportable(core, ('ds:abc', 'x', '', '', '', '', '')))
            with self.assertRaises(packages.PackageError):
                mm.ManagerCore.export_package(core, ('ds:abc', 'x', '', '', '', '', ''), tmp)
