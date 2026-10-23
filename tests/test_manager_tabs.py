"""The Procedures tab's three views (Automated Calibrations / Manual Calibrations / Adjustment): how a procedure is classified, the optional sidecar field `kind`, and that the
field passes through the package build / inspect / install unchanged.  No tkinter needed (the windows are checked by `checks_manager_tabs` in
tests/real_tk_checks.py, run by tests/test_beta_real_tk_windows.py).   Run:  python -m unittest tests.test_manager_tabs"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import packages as P  # noqa: E402
import procscan  # noqa: E402
import verified as V  # noqa: E402
from tests._pkg_helpers import make_tree, read_zip  # noqa: E402

K2 = 'Keithley_2000_Verification'
LEGACY = json.loads((ROOT / 'tests' / 'fixtures' / 'legacy_registry.json').read_text(encoding='utf-8'))


def sidecar(**kw):
    d = json.loads((ROOT / 'Procedures' / f'{K2}.procedure.json').read_text(encoding='utf-8'))
    d.update(kw)
    return d


class Classify(unittest.TestCase):
    def test_default_by_category_or_name(self):
        c = procscan.classify
        self.assertEqual(c('Fluke 8846A Guided Adjustment', 'Digital Multimeter Adjustment'), 'adjustment')
        self.assertEqual(c('Keithley 2000 Adjustment', 'Digital Multimeter'), 'adjustment')           # name alone
        self.assertEqual(c('Keithley 2000 Calibration', 'Digital Multimeter Adjustment'), 'adjustment')   # category alone
        self.assertEqual(c('X', 'Digital Multimeter ADJUSTMENT'), 'adjustment')
        self.assertEqual(c('Keithley 2000 Performance Verification', 'Digital Multimeter'), 'verification')
        self.assertEqual(c('', ''), 'verification')

    def test_explicit_kind_wins_over_the_text(self):
        self.assertEqual(procscan.classify('Fluke 8846A Guided Adjustment', 'Digital Multimeter Adjustment', 'verification'), 'verification')
        self.assertEqual(procscan.classify('Some Procedure', 'Oscilloscope', 'adjustment'), 'adjustment')
        self.assertEqual(procscan.classify('Some Adjustment', 'x', 'Adjustment'), 'adjustment')          # case does not matter
        self.assertEqual(procscan.classify('Some Adjustment', 'x', 'nonsense'), 'adjustment')            # not a valid kind: the default applies
        self.assertEqual(procscan.classify('Some Procedure', 'Digital Multimeter', 'manual'), 'manual')   # the new Manual Calibrations kind
        self.assertEqual(procscan.classify('Some Adjustment', 'x', 'manual'), 'manual')                   # explicit kind wins over the wording

    def test_manual_is_never_a_default(self):
        """Only an explicit sidecar kind (or a saved datasheet's kind) puts a procedure in Manual Calibrations; no wording does, so nothing moves tabs by itself."""
        for name, cat in (('Manual Calibration', 'Manual'), ('Hand-entered', 'manual calibrations')):
            self.assertEqual(procscan.classify(name, cat), 'verification')
        self.assertEqual(procscan.KINDS, ('verification', 'adjustment', 'manual'))

    def test_installed_procedures(self):
        by = {p.id: p.effective_kind for p in procscan.procs(ROOT)}
        self.assertEqual([k for k, v in by.items() if v == 'adjustment'], ['Fluke_8846A_Adjustment', 'Keithley_2000_Adjustment', 'Fluke_8808A_Adjustment'])
        self.assertEqual(by['Fluke_8846A_Verification'], 'verification')
        self.assertTrue(all(v == 'verification' for k, v in by.items() if k not in ('Fluke_8808A_Adjustment', 'Fluke_8846A_Adjustment', 'Keithley_2000_Adjustment')))
        self.assertGreater(len(by), 20)

    def test_every_registered_adjustment_by_category_name_is_in_the_adjustment_view(self):
        for p in procscan.procs(ROOT):
            if 'adjust' in f'{p.name} {p.category}'.lower():
                self.assertEqual(p.effective_kind, 'adjustment', p.id)


class SidecarKind(unittest.TestCase):
    def test_field_is_optional_and_parsed(self):
        self.assertEqual(procscan.parse_sidecar(sidecar(), K2).kind, '')
        self.assertEqual(procscan.parse_sidecar(sidecar(kind='adjustment'), K2).effective_kind, 'adjustment')
        self.assertEqual(procscan.parse_sidecar(sidecar(kind='verification', name='K2 Adjustment'), K2).effective_kind, 'verification')
        self.assertEqual(procscan.parse_sidecar(sidecar(kind='manual'), K2).effective_kind, 'manual')
        self.assertEqual(procscan.parse_sidecar(sidecar(kind=None), K2).kind, '')

    def test_bad_value_is_refused_like_any_other_bad_field(self):
        for bad in ('calibration', 3, ['adjustment'], True):
            with self.assertRaises(procscan.ScanProblem, msg=repr(bad)):
                procscan.parse_sidecar(sidecar(kind=bad), K2)

    def test_future_adjustment_procedure_lands_in_the_adjustment_view_with_no_manager_change(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / 'Procedures'
            folder.mkdir()
            for pid, extra in (('K2000_Adjust_A', {}), ('K2000_Adjust_B', {'kind': 'adjustment', 'category': 'Digital Multimeter', 'name': 'Keithley 2000 Cal B'})):
                doc = sidecar(id=pid, launcher=f'Procedures/{pid}.py', fingerprint={'code': [f'Procedures/{pid}.py'], 'spec': []}, own_files=[],
                              name=f'Keithley 2000 Adjustment {pid[-1]}', category='Digital Multimeter Adjustment')
                doc.update(extra)
                (folder / f'{pid}.procedure.json').write_text(json.dumps(doc), encoding='utf-8')
            res = procscan.scan_folder(folder)
            self.assertEqual(res.problems, [])
            self.assertEqual([p.effective_kind for p in res.procs], ['adjustment', 'adjustment'])

    def test_registration_tuple_and_the_legacy_fixture_do_not_depend_on_kind(self):
        procs = procscan.procs(ROOT)
        self.assertEqual([list(p.registration) for p in procs], LEGACY['records'])
        self.assertEqual(len(procscan.Proc('a', 'b', kind='adjustment').registration), 5)

    def test_manager_source_has_the_three_tabs_and_the_notes(self):
        src = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        self.assertIn("'  Automated Calibrations  '", src)
        self.assertIn("'  Manual Calibrations  '", src)
        self.assertIn("'  Adjustment  '", src)
        self.assertNotIn('Performance Verification', src)
        self.assertIn("changes the instrument's calibration", src)
        self.assertIn('type each reading into the test point grid', src)

    def test_manager_has_no_instruments_tab_but_keeps_the_instruments_table(self):
        """The Instruments tab was removed (assets are tracked in other software); the table stays in calibration_procedures.sqlite3 because labregistry reads it.
        The start-up of the Manager with a real instruments table is checked on a real Tk (`checks_manager_tabs`)."""
        src = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        self.assertNotIn("'  Instruments  '", src)
        for gone in ('instruments_frame', 'build_instruments_tab', 'refresh_instruments', 'instrument_editor', 'launch_instrument_procedure', 'selected_instrument',
                     'Instruments tab'):
            self.assertNotIn(gone, src)
        self.assertIn('CREATE TABLE IF NOT EXISTS instruments', src)             # schema creation / migration unchanged
        self.assertNotIn('DROP TABLE', src)
        import re
        tabs = re.findall(r"self\.notebook\.add\(self\.\w+, text='\s*([^']+?)\s*'\)", src)
        self.assertEqual(tabs, ['Procedures', 'Asset History', 'Standards Specs', 'Mudcats Datasheet Importer', 'Datasheet Builder', 'Procedure Development'])
        self.assertIn('FROM instruments', (ROOT / 'labregistry.py').read_text(encoding='utf-8'))

    def test_user_datasheet_rows_carry_their_kind(self):
        import dsb_manager
        import datasheet_builder as db
        import dsb_fixtures as fx
        with tempfile.TemporaryDirectory() as d:
            root, reg = Path(d) / 'us', Path(d) / 'reg.sqlite3'
            auto = fx.dmm_34461a_like()
            self.assertTrue(db.save(auto, root=root, db=reg).ok)
            hand = fx.dmm_34461a_like()
            hand.title = 'Hand entered'
            hand.options['manual_entry'] = True
            import datasheet_builder_rules as rules                  # a manual sheet sources nothing: its missing uncertainties are waived for the whole sheet (rule 5)
            rules.set_waiver(hand, [rules.WHOLE_SHEET], 'manual_calibration', '', who='test')
            self.assertTrue(db.save(hand, root=root, db=reg).ok)
            kinds = {r['name']: r['kind'] for r in dsb_manager.user_rows(root=root, db=reg)}
            self.assertEqual(sorted(kinds.values()), ['manual', 'verification'])
            self.assertEqual(kinds[[n for n in kinds if 'Hand' in n][0]], 'manual')

    def test_registry_without_the_kind_column_is_migrated(self):
        import sqlite3
        import datasheet_builder as db
        import dsb_fixtures as fx
        with tempfile.TemporaryDirectory() as d:
            root, reg = Path(d) / 'us', Path(d) / 'old.sqlite3'
            con = sqlite3.connect(reg)
            con.executescript(db.REG_SCHEMA.replace(",\n    kind TEXT NOT NULL DEFAULT ''", ''))
            con.commit(); con.close()
            self.assertNotIn('kind', {r[1] for r in sqlite3.connect(reg).execute('PRAGMA table_info(user_datasheets)')})
            self.assertTrue(db.save(fx.dmm_34461a_like(), root=root, db=reg).ok)
            self.assertEqual([r['kind'] for r in db.list_datasheets(root=root, db=reg)], ['verification'])


class PackagesKeepKind(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.src = make_tree(self.t / 'src', [K2])
        side = self.src / 'Procedures' / f'{K2}.procedure.json'
        doc = json.loads(side.read_text(encoding='utf-8'))
        doc['kind'] = 'verification'                                  # an explicit kind in the source procedure's sidecar
        side.write_text(json.dumps(doc, indent=1) + '\n', encoding='utf-8')
        clock = lambda: datetime(2026, 10, 22, 9, 0, 0)  # noqa: E731
        self.src_reg = V.Registry(self.t / 'src.sqlite3', base=self.src, now=clock)
        self.tree = make_tree(self.t / 'target', (), (K2,))
        self.reg = V.Registry(self.t / 'target.sqlite3', base=self.tree, now=clock)

    def test_package_carries_kind_and_installs_it(self):
        zp = P.build_package(K2, self.src, self.t / 'lib', registry=self.src_reg, author='t', created='2026-10-22T09:00:00')
        self.assertEqual(json.loads(read_zip(zp)[f'Procedures/{K2}.procedure.json'])['kind'], 'verification')
        pv = P.inspect(zp, self.tree, self.reg)
        self.assertEqual(pv.errors, [])
        P.install(zp, self.tree, self.reg, expected_sha256=pv.zip_sha256, imported_by='t', now=lambda: datetime(2026, 10, 22, 10, 0))
        self.assertEqual(procscan.find(K2, self.tree).kind, 'verification')

    def test_package_with_a_bad_kind_is_refused_with_a_reason(self):
        zp = P.build_package(K2, self.src, self.t / 'lib', registry=self.src_reg, author='t', created='2026-10-22T09:00:00')
        from tests._pkg_helpers import rewrite_zip

        def edit(members):
            doc = json.loads(members[f'Procedures/{K2}.procedure.json'])
            doc['kind'] = 'repair'
            members[f'Procedures/{K2}.procedure.json'] = json.dumps(doc).encode()
        rewrite_zip(zp, edit)
        pv = P.inspect(zp, self.tree, self.reg)
        self.assertTrue(pv.errors)                                   # refused (a changed file also fails its checksum); nothing installed
        self.assertFalse((self.tree / 'Procedures' / f'{K2}.py').exists())


if __name__ == '__main__':
    unittest.main()
