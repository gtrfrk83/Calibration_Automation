"""Procedures register themselves (procscan.py): the scanned list equals the hand-written registrations it replaced, and the sidecar rules.
No tkinter needed (the Manager itself is imported under the stub).   Run:  python -m unittest tests.test_procscan"""
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import procscan  # noqa: E402
import verified  # noqa: E402

LEGACY = json.loads((ROOT / 'tests' / 'fixtures' / 'legacy_registry.json').read_text(encoding='utf-8'))


class ScannedEqualsOldRegistry(unittest.TestCase):
    """tests/fixtures/legacy_registry.json is the hand-written Manager list, STABLE, VERSIONS, verified.FILES and verified.SEED as they were on main
    (59cfe1c), before procedures registered themselves."""

    def test_registration_list_is_identical_and_in_the_same_order(self):
        self.assertEqual([list(p.registration) for p in procscan.procs(ROOT)], LEGACY['records'])

    def test_stable_and_versions_are_identical(self):
        stable, versions = procscan.legacy_tables(procscan.procs(ROOT))
        self.assertEqual(stable, LEGACY['STABLE'])
        self.assertEqual(versions, LEGACY['VERSIONS'])
        self.assertEqual(list(stable), list(LEGACY['STABLE']))                      # same order too

    def test_seeded_list_is_identical(self):
        self.assertEqual(list(verified.SEED), LEGACY['SEED'])
        self.assertEqual(procscan.seed_list(procscan.procs(ROOT)), tuple(LEGACY['SEED']))

    def test_no_scan_problems_and_no_unregistered_launcher(self):
        result = procscan.scan_folder(ROOT / 'Procedures')
        self.assertEqual(result.problems, [])
        launchers = {p.name for p in (ROOT / 'Procedures').glob('*.py')} - {'User_Datasheet.py', '__init__.py'}
        self.assertEqual({p.launcher_name for p in result.procs}, launchers)

    def test_every_declared_file_exists_and_diagram_prefixes_match_hookups(self):
        for p in procscan.procs(ROOT):
            for label in (*p.fingerprint_code, *p.fingerprint_spec, *p.own_files, *p.tests, p.launcher, p.sidecar):
                self.assertTrue((ROOT / procscan.split_label(label)[0]).is_file(), (p.id, label))
            self.assertTrue(set(p.own_files) <= {procscan.split_label(l)[0] for l in p.own_files})
            if p.hookup_meter:
                import hookups
                self.assertIn(p.hookup_meter, hookups.METERS, p.id)
                self.assertIn(f'hook_{p.hookup_meter}', p.diagram_prefixes)

    def test_old_fingerprint_files_are_a_superset_of_the_new_ones(self):
        """The new declared lists only DROP what a procedure does not use (hookups.py of the meter-less 287/289); the one addition is surprise.py
        (stop-on-surprise, owner-approved: it is listed by the engines that import it), and the UI-port files of an engine ported to ui_port (ui_port.py,
        ui_port_tk.py, <engine>_view_tk.py and its Qt twin <engine>_view_qt.py and the WaveSurfer Qt helper modules wavesurfer_qt_*.py: the code that shows its prompts and window; Qt migration, owner-approved)."""
        for key, old in LEGACY['FILES'].items():
            new = verified.FILES[key]
            added = {'surprise.py'} | {f for f in new['code'] if f in ('ui_port.py', 'ui_port_tk.py') or f.endswith(('_view_tk.py', '_view_qt.py')) or f.startswith('wavesurfer_qt_')}
            self.assertLessEqual(set(new['code']) - added, set(old['code']), key)
            self.assertEqual(new['spec'], old['spec'], key)
            self.assertEqual(set(old['code']) - set(new['code']), {'hookups.py'} if key in ('Fluke_287_Verification.py', 'Fluke_289_Verification.py') else set(), key)

    def test_handheld_specs_name_the_same_hookup_meter_as_the_sidecar(self):
        for p in procscan.procs(ROOT):
            metas = [json.loads((ROOT / s).read_text(encoding='utf-8')).get('options', {}).get('hookup_meter') for s in p.specs]
            self.assertEqual(p.hookup_meter or None, next((m for m in metas if m), None), p.id)


class ManagerUsesTheScan(unittest.TestCase):
    def test_init_db_registers_the_scanned_procedures_in_order(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        spec = importlib.util.spec_from_file_location('tk_stub', ROOT / 'tests' / '_tk_stub.py')
        stub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stub)
        stub.install()
        old = os.environ.get('CALSUITE_DATA')
        with tempfile.TemporaryDirectory() as d:
            os.environ['CALSUITE_DATA'] = d
            self.addCleanup(lambda: os.environ.__setitem__('CALSUITE_DATA', old) if old is not None else os.environ.pop('CALSUITE_DATA', None))
            for name in ('appdata', 'Calibration_Procedure_Manager'):
                sys.modules.pop(name, None)
            try:
                import Calibration_Procedure_Manager as M
            except Exception as exc:
                self.skipTest(f'Manager not importable here: {exc}')
            self.addCleanup(sys.modules.pop, 'Calibration_Procedure_Manager', None)
            M.init_db()
            with sqlite3.connect(M.DB) as conn:
                rows = conn.execute('SELECT name,manufacturer,model,category,script_path,description FROM procedures ORDER BY id').fetchall()
            self.assertEqual([[r[0], r[1], r[2], r[3], Path(r[4]).name] for r in rows], LEGACY['records'])
            self.assertTrue(all(Path(r[4]).parent.as_posix() == 'Procedures' and r[5] == 'Standalone calibration procedure' for r in rows))
            self.assertEqual(M.STABLE, LEGACY['STABLE'])
            self.assertEqual(M.VERSIONS, LEGACY['VERSIONS'])
            before = rows
            M.init_db()                                                           # running it again changes nothing
            with sqlite3.connect(M.DB) as conn:
                self.assertEqual(conn.execute('SELECT name,manufacturer,model,category,script_path,description FROM procedures ORDER BY id').fetchall(), before)

    def test_the_manager_no_longer_lists_procedures_by_hand(self):
        src = (ROOT / 'Calibration_Procedure_Manager.py').read_text(encoding='utf-8')
        self.assertNotIn('Keysight_34465A_Verification.py', src)
        self.assertIn('procscan', src)


class SidecarRules(unittest.TestCase):
    def doc(self, **kw):
        d = json.loads((ROOT / 'Procedures' / 'Keithley_2000_Verification.procedure.json').read_text(encoding='utf-8'))
        d.update(kw)
        return d

    def bad(self, doc, stem='Keithley_2000_Verification'):
        with self.assertRaises(procscan.ScanProblem):
            procscan.parse_sidecar(doc, stem)

    def test_good_sidecar_parses(self):
        p = procscan.parse_sidecar(self.doc(), 'Keithley_2000_Verification')
        self.assertEqual((p.id, p.key, p.model), ('Keithley_2000_Verification', 'Keithley_2000_Verification.py', '2000'))

    def test_bad_sidecars_are_refused(self):
        self.bad(self.doc(schema=2))
        self.bad(self.doc(id='Other'))
        self.bad(self.doc(name=' '))
        self.bad(self.doc(launcher='Procedures/Other.py'))
        self.bad(self.doc(fingerprint={'code': ['Procedures/Other.py'], 'spec': []}))                     # launcher missing from the fingerprint
        self.bad(self.doc(fingerprint={'code': ['Procedures/Keithley_2000_Verification.py', '../x.py'], 'spec': []}))
        self.bad(self.doc(fingerprint={'code': ['Procedures/Keithley_2000_Verification.py', '/etc/passwd'], 'spec': []}))
        self.bad(self.doc(own_files=['C:/x.py']))
        self.bad(self.doc(order='1'))
        self.bad(self.doc(drivers=['../x']))
        self.bad([])

    def test_a_bad_sidecar_is_skipped_not_fatal_and_duplicates_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / 'Procedures'
            folder.mkdir()
            good = self.doc()
            (folder / 'Keithley_2000_Verification.procedure.json').write_text(json.dumps(good), encoding='utf-8')
            (folder / 'Broken.procedure.json').write_text('{not json', encoding='utf-8')
            dup = self.doc(id='Copy_Verification')
            dup['launcher'] = 'Procedures/Copy_Verification.py'
            dup['fingerprint'] = {'code': ['Procedures/Copy_Verification.py'], 'spec': []}
            (folder / 'Copy_Verification.procedure.json').write_text(json.dumps(dup), encoding='utf-8')     # same display name as the first
            result = procscan.scan_folder(folder)
            self.assertEqual(len(result.procs), 1)                                    # the first by file name wins; the same display name twice is reported
            loser = {'Copy_Verification': 'Keithley_2000_Verification', 'Keithley_2000_Verification': 'Copy_Verification'}[result.procs[0].id]
            self.assertEqual({n for n, _r in result.problems}, {'Broken.procedure.json', loser + '.procedure.json'})

    def test_order_decides_the_list_order(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / 'Procedures'
            folder.mkdir()
            for stem, order in (('B_Proc', 1), ('A_Proc', 2), ('C_Proc', 1)):
                doc = {'schema': 1, 'id': stem, 'name': stem, 'order': order, 'fingerprint': {'code': [f'Procedures/{stem}.py'], 'spec': []}}
                (folder / f'{stem}.procedure.json').write_text(json.dumps(doc), encoding='utf-8')
            self.assertEqual([p.id for p in procscan.scan_folder(folder).procs], ['B_Proc', 'C_Proc', 'A_Proc'])

    def test_scan_cache_notices_a_new_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'Procedures').mkdir()
            self.assertEqual(procscan.procs(d), [])
            doc = {'schema': 1, 'id': 'New_Proc', 'name': 'New', 'fingerprint': {'code': ['Procedures/New_Proc.py'], 'spec': []}}
            (Path(d) / 'Procedures' / 'New_Proc.procedure.json').write_text(json.dumps(doc), encoding='utf-8')
            self.assertEqual([p.id for p in procscan.procs(d)], ['New_Proc'])


if __name__ == '__main__':
    unittest.main()
