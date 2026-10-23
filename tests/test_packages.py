"""Procedure packages (packages.py, tools/make_package.py): round trip, tampering, zip-slip, backups, verified marks, the library folder setting.
Everything uses throw-away folders; the real suite folder, the real registry and calibration_procedures.sqlite3 are never touched.
Run:  python -m unittest tests.test_packages"""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import packages as P  # noqa: E402
import procscan  # noqa: E402
import verified as V  # noqa: E402
from tests._pkg_helpers import craft_zip, make_tree, read_zip, rewrite_zip, sha  # noqa: E402

K2 = 'Keithley_2000_Verification'
H117 = 'Fluke_117_Verification'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.src = make_tree(self.t / 'src', [K2])
        self.out = self.t / 'lib'
        self.clock = [datetime(2026, 10, 22, 9, 0, 0)]
        self.src_reg = V.Registry(self.t / 'src_registry.sqlite3', base=self.src, now=lambda: self.clock[0])

    def target(self, proc_ids=(), shared_for=(K2,), name='target'):
        tree = make_tree(self.t / name, proc_ids, shared_for)
        reg = V.Registry(self.t / f'{name}_registry.sqlite3', base=tree, now=lambda: self.clock[0])
        return tree, reg

    def package(self, proc=K2, **kw):
        return P.build_package(proc, self.src, self.out, registry=self.src_reg, author='Mike', created='2026-10-22T09:00:00', **kw)

    def tree_snapshot(self, tree):
        return {p.relative_to(tree).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(tree).rglob('*')) if p.is_file()}

    def verify_in(self, reg, tree, pid=K2, who='Mike', on_date='2026-10-20'):
        proc = procscan.find(pid, tree)
        entry = V.make_entry(proc.name, proc.model, tree / proc.launcher, tree)
        return reg.verify(entry, who, on_date, 'ran clean', 'Instrument: 2000 SN 1', today=date(2026, 10, 22)), entry


class RoundTrip(Base):
    def test_make_then_import_into_a_temp_tree(self):
        zp = self.package()
        self.assertEqual(zp.name, f'{K2}_v1.zip')
        members = read_zip(zp)
        self.assertEqual(set(members), {'manifest.json', f'Procedures/{K2}.py', f'Procedures/{K2}.procedure.json', 'drivers/keithley_2000.py',
                                         'specs/keithley_2000_pv.json', 'tests/test_k2000_points.py'})
        man = json.loads(members['manifest.json'])
        self.assertEqual((man['package_format'], man['procedure']['id'], man['author']), (1, K2, 'Mike'))
        self.assertTrue(all(f['sha256'] == sha(members[f['path']]) for f in man['files']))
        self.assertIn('keithley2000_verification.py', man['requires'])                       # shared engine: required, not shipped
        self.assertNotIn('keithley2000_verification.py', members)

        tree, reg = self.target()
        sentinel = tree / 'calibration_procedures.sqlite3'
        sentinel.write_bytes(b'SQLite format 3\x00 pretend library')
        before_sentinel = sentinel.read_bytes()
        lib = self.out
        pv = P.inspect(zp, tree, reg, library_dir=str(lib))
        self.assertTrue(pv.ok, pv.errors)
        self.assertEqual((pv.proc_id, pv.version, pv.in_library, pv.author), (K2, '1', True, 'Mike'))
        self.assertEqual({f.state for f in pv.files}, {'new'})
        self.assertFalse(pv.is_update)
        self.assertEqual(pv.status_kind, 'none')
        self.assertEqual(procscan.find(K2, tree), None)                                      # inspecting wrote nothing

        res = P.install(zp, tree, reg, expected_sha256=pv.zip_sha256, library_dir=str(lib), imported_by='tester', now=lambda: datetime(2026, 10, 22, 10, 0))
        self.assertEqual(sorted(res.written), sorted(m for m in members if m != 'manifest.json'))
        self.assertEqual(res.backups, [])
        for rel, raw in members.items():
            if rel != 'manifest.json':
                self.assertEqual((tree / rel).read_bytes(), raw, rel)
        found = procscan.find(K2, tree)                                                      # the scanner picks the new procedure up
        self.assertEqual(found.name, 'Keithley 2000 Performance Verification')
        self.assertEqual(sentinel.read_bytes(), before_sentinel)                             # calibration_procedures.sqlite3 is never touched
        self.assertEqual({p.name for p in tree.iterdir()} & {'lab_registry.sqlite3'}, set())
        rows = P.imports(reg.path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r['procedure'], r['version'], r['zip_sha256'], r['imported_by'], r['imported_at'], r['author']),
                         (K2, '1', pv.zip_sha256, 'tester', '2026-10-22T10:00:00', 'Mike'))
        self.assertEqual(sorted(f['path'] for f in r['files']), sorted(res.written))
        self.assertTrue(all(f['sha256'] == sha((tree / f['path']).read_bytes()) for f in r['files']))
        con = sqlite3.connect(reg.path)
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("UPDATE package_imports SET procedure='x'")
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute('DELETE FROM package_imports')
        con.close()

    def test_importing_the_same_package_again_changes_nothing(self):
        zp = self.package()
        tree, reg = self.target()
        P.install(zp, tree, reg)
        snap = self.tree_snapshot(tree)
        pv = P.inspect(zp, tree, reg)
        self.assertEqual({f.state for f in pv.files}, {'same'})
        res = P.install(zp, tree, reg)
        self.assertEqual((res.written, res.backups, res.unlocked), ([], [], False))
        self.assertEqual(self.tree_snapshot(tree), snap)
        self.assertEqual(len(P.imports(reg.path)), 2)

    def test_the_zip_is_reproducible(self):
        a = self.package()
        first = a.read_bytes()
        b = P.build_package(K2, self.src, self.t / 'again', registry=self.src_reg, author='Mike', created='2026-10-22T09:00:00')
        self.assertEqual(first, b.read_bytes())

    def test_command_line_tool_writes_the_package(self):
        import runpy
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        sys.argv = ['make_package.py']
        ns = runpy.run_path(str(ROOT / 'tools' / 'make_package.py'))
        with redirect_stdout(buf):
            code = ns['main']([K2, '--base', str(self.src), '--out', str(self.t / 'cli'), '--author', 'cli', '--registry', str(self.t / 'cli_reg.sqlite3')])
        self.assertEqual(code, 0)
        self.assertTrue((self.t / 'cli' / f'{K2}_v1.zip').is_file())
        self.assertIn('sha256', buf.getvalue())
        self.assertEqual(ns['main']([K2, '--base', str(self.src), '--out', str(self.t / 'cli2'), '--verified-mark', '--registry', str(self.t / 'cli_reg.sqlite3')]), 2)

    def test_no_nothing_exported_for_an_unknown_procedure(self):
        with self.assertRaises(P.PackageError):
            P.build_package('Nope', self.src, self.out)

    def test_missing_requirements_are_refused_and_named(self):
        zp = self.package()
        tree, reg = self.target(shared_for=())                                               # no engine, no calibrator driver here
        pv = P.inspect(zp, tree, reg)
        self.assertFalse(pv.ok)
        self.assertIn('keithley2000_verification.py', ' '.join(pv.errors))
        with self.assertRaises(P.PackageError):
            P.install(zp, tree, reg)
        self.assertFalse((tree / 'Procedures' / f'{K2}.py').exists())

    def test_a_changed_file_since_the_preview_is_refused(self):
        zp = self.package()
        tree, reg = self.target()
        pv = P.inspect(zp, tree, reg)
        rewrite_zip(zp, lambda m: m.update({'extra.txt': b'x'}))
        with self.assertRaises(P.PackageError):
            P.install(zp, tree, reg, expected_sha256=pv.zip_sha256)

    def test_exported_sidecar_never_carries_the_seeded_flag_and_the_importer_keeps_the_owners_own(self):
        src = make_tree(self.t / 'src117', [H117])
        zp = P.build_package(H117, src, self.out, registry=V.Registry(self.t / 'r117.sqlite3', base=src))
        side = json.loads(read_zip(zp)[f'Procedures/{H117}.procedure.json'])
        self.assertIs(side['seed_verified'], False)
        self.assertNotIn('seed_order', side)
        tree, reg = self.target([H117], shared_for=())                                       # an installation that has it, seeded
        installed = json.loads((tree / 'Procedures' / f'{H117}.procedure.json').read_text())
        self.assertTrue(installed['seed_verified'])
        # edit the launcher inside the package to force a replacement
        def edit(m):
            m[f'Procedures/{H117}.py'] += b'\n# v2\n'
            man = json.loads(m['manifest.json'])
            for f in man['files']:
                if f['path'] == f'Procedures/{H117}.py':
                    f['sha256'], f['size'] = sha(m[f['path']]), len(m[f['path']])
            m['manifest.json'] = json.dumps(man).encode()
        rewrite_zip(zp, edit)
        P.install(zp, tree, reg)
        after = json.loads((tree / 'Procedures' / f'{H117}.procedure.json').read_text())
        self.assertEqual((after['seed_verified'], after['seed_order']), (True, installed['seed_order']))
        self.assertIn(H117, [s['proc_key'][:-3] for s in procscan.seed_list(procscan.procs(tree))])


class Refusals(Base):
    """Every refusal leaves the target tree exactly as it was."""

    def good_files(self):
        return {k: v for k, v in read_zip(self.package()).items() if k != 'manifest.json'}

    def refused(self, zp, *needles, tree=None):
        tree, reg = (tree, V.Registry(self.t / 'rr.sqlite3', base=tree)) if tree else self.target()
        before = self.tree_snapshot(tree)
        pv = P.inspect(zp, tree, reg)
        self.assertFalse(pv.ok, 'should have been refused')
        text = ' | '.join(pv.errors).lower()
        for n in needles:
            self.assertIn(n.lower(), text)
        with self.assertRaises(P.PackageError):
            P.install(zp, tree, reg)
        self.assertEqual(self.tree_snapshot(tree), before)
        self.assertFalse((tree / 'Backups').exists())
        return pv

    def test_tampered_file(self):
        zp = self.package()
        rewrite_zip(zp, lambda m: m.__setitem__(f'Procedures/{K2}.py', m[f'Procedures/{K2}.py'] + b'\nimport os\n'))
        self.refused(zp, 'checksum does not match')

    def test_missing_or_malformed_checksum(self):
        files = self.good_files()
        listed = [{'path': p, 'sha256': sha(r)} for p, r in files.items()]
        listed[0].pop('sha256')
        self.refused(craft_zip(self.t / 'a.zip', files, listed=listed), 'checksum missing')
        listed = [{'path': p, 'sha256': 'ABC'} for p, r in files.items()]
        self.refused(craft_zip(self.t / 'b.zip', files, listed=listed), 'checksum missing')

    def test_unlisted_and_missing_files(self):
        files = self.good_files()
        self.refused(craft_zip(self.t / 'a.zip', files, raw_entries=[('specs/sneaky.json', b'{}')]), 'not listed in the manifest')
        listed = [{'path': p, 'sha256': sha(r)} for p, r in files.items()] + [{'path': 'specs/ghost.json', 'sha256': sha(b'{}')}]
        self.refused(craft_zip(self.t / 'b.zip', files, listed=listed), 'not in the zip')

    def test_zip_slip_and_path_tricks(self):
        files = self.good_files()
        bad = ['../evil.py', 'Procedures/../../evil.py', '/etc/evil.py', 'C:/evil.py', 'Procedures\\evil.py', 'Procedures/./x.py', 'Procedures//x.py',
               'Procedures/.hidden.py', 'Procedures/x.py:stream', 'Procedures/CON.py', 'Procedures/name.py ']
        for i, name in enumerate(bad):
            with self.subTest(name):
                data = dict(files)
                data[name] = b'x = 1\n'
                self.refused(craft_zip(self.t / f'slip{i}.zip', data), 'evil' if 'evil' in name else name.split('/')[-1][:6])

    def test_files_outside_the_allowed_folders_and_executable_names(self):
        files = self.good_files()
        cases = {'evil.py': 'outside the allowed', 'Backups/x.py': 'outside the allowed', 'Calibration_Procedure_Manager.py': 'outside the allowed',
                 'Procedures': 'outside the allowed', 'tools/make_package.py': 'outside the allowed', 'verified.py': 'outside the allowed',
                 'Procedures/run.exe': 'executable', 'Procedures/run.bat': 'executable', 'drivers/x.dll': 'executable', 'specs/x.sh': 'executable',
                 'tests/x.ps1': 'executable', 'drivers/x.sqlite3': 'executable or database', 'Procedures/x.pyc': 'executable', 'specs/x.zip': 'executable',
                 'specs/noext': 'not allowed', 'specs/x.xlsx': 'not allowed', 'diagrams/x.py': 'diagrams folder', 'diagrams/x.exe': 'executable'}
        for i, (name, why) in enumerate(cases.items()):
            with self.subTest(name):
                data = dict(files)
                data[name] = b'x'
                self.refused(craft_zip(self.t / f'out{i}.zip', data), why)

    def test_symbolic_link_entry(self):
        files = self.good_files()
        zp = craft_zip(self.t / 'link.zip', files)
        with zipfile.ZipFile(zp, 'a') as zf:
            zi = zipfile.ZipInfo('Procedures/link.py')
            zi.external_attr = (0o120777 << 16)
            zf.writestr(zi, '../../etc/passwd')
        self.refused(zp, 'symbolic link')

    def test_not_a_zip_and_missing_manifest_and_bad_manifest(self):
        bad = self.t / 'junk.zip'
        bad.write_bytes(b'this is not a zip')
        self.refused(bad, 'not a readable zip')
        zp = self.t / 'nomanifest.zip'
        with zipfile.ZipFile(zp, 'w') as zf:
            zf.writestr(f'Procedures/{K2}.py', 'x=1')
        self.refused(zp, 'no manifest.json')
        files = self.good_files()
        self.refused(craft_zip(self.t / 'm1.zip', files, manifest={'package_format': 1}), 'procedure id')
        self.refused(craft_zip(self.t / 'm2.zip', files, package_format=2), 'newer package format')
        self.refused(craft_zip(self.t / 'm3.zip', files, min_suite_version='v999'), 'needs suite version')
        self.refused(craft_zip(self.t / 'm4.zip', files, procedure={'id': '../x', 'name': 'n', 'version': '1'}), 'plain name')

    def test_python_that_does_not_parse_is_refused_not_run(self):
        files = self.good_files()
        marker = self.t / 'ran.txt'
        files[f'Procedures/{K2}.py'] = f"open({str(marker)!r}, 'w').write('ran')\ndef broken(:\n".encode()
        self.refused(craft_zip(self.t / 'syn.zip', files), 'not valid python')
        self.assertFalse(marker.exists())

    def test_sidecar_problems(self):
        files = self.good_files()
        side = f'Procedures/{K2}.procedure.json'
        no_side = {k: v for k, v in files.items() if k != side}
        self.refused(craft_zip(self.t / 'ns.zip', no_side), 'metadata')
        doc = json.loads(files[side])
        for i, (change, needle) in enumerate(((dict(seed_verified=True), 'seeded-verified'), (dict(seed_order=1), 'seeded-verified'), (dict(version='9'), 'version'),
                                              (dict(name='Other Name'), 'name'), (dict(schema=7), 'schema'))):
            with self.subTest(change):
                d = dict(files)
                d[side] = json.dumps({**doc, **change}).encode()
                self.refused(craft_zip(self.t / f'sc{i}.zip', d), needle)

    def test_display_name_already_used_by_another_procedure(self):
        tree, reg = self.target([H117], shared_for=())
        files = self.good_files()
        side = f'Procedures/{K2}.procedure.json'
        files[side] = json.dumps({**json.loads(files[side]), 'name': 'Fluke 117 Performance Verification'}).encode()
        zp = craft_zip(self.t / 'dupname.zip', files, proc={'id': K2, 'name': 'Fluke 117 Performance Verification', 'version': '1'})
        self.refused(zp, 'already has the display name', tree=make_tree(self.t / 'withk2', [H117], [K2]))

    def test_oversized_package(self):
        zp = self.package()
        with mock.patch.object(P, 'MAX_ZIP', 100):
            self.refused(zp, 'too large')

    def test_a_directory_entry_with_dotdot(self):
        zp = craft_zip(self.t / 'dir.zip', self.good_files(), raw_entries=[('../escape/', b'')])
        self.refused(zp, '..')

    def test_install_writes_nothing_outside_the_tree(self):
        zp = self.package()
        tree, reg = self.target()
        before = {p for p in self.t.rglob('*') if p.is_file()}
        P.install(zp, tree, reg)
        new = {p for p in self.t.rglob('*') if p.is_file()} - before
        self.assertTrue(new and all(tree in p.parents or p == reg.path for p in new), [str(p) for p in new if tree not in p.parents])


class ReplaceAndBackup(Base):
    def old_target(self):
        tree, reg = self.target([K2], shared_for=())
        (tree / f'Procedures/{K2}.py').write_text('# OLD launcher\n', encoding='utf-8')
        (tree / 'specs/keithley_2000_pv.json').write_text('{"old": true}', encoding='utf-8')
        return tree, reg

    def test_replaced_files_are_backed_up_first_with_a_version_number(self):
        zp = self.package()
        tree, reg = self.old_target()
        pv = P.inspect(zp, tree, reg)
        self.assertTrue(pv.ok)
        states = {f.path: f.state for f in pv.files}
        self.assertEqual((states[f'Procedures/{K2}.py'], states['specs/keithley_2000_pv.json'], states['drivers/keithley_2000.py']), ('replace', 'replace', 'same'))
        self.assertEqual(sorted(pv.replaced), [f'Procedures/{K2}.py', 'specs/keithley_2000_pv.json'])
        res = P.install(zp, tree, reg)
        b1 = tree / 'Backups/packages/Procedures' / f'{K2}_backup_v01.py'
        b2 = tree / 'Backups/packages/specs/keithley_2000_pv_backup_v01.json'
        self.assertEqual(b1.read_text(), '# OLD launcher\n')
        self.assertEqual(b2.read_text(), '{"old": true}')
        self.assertEqual(sorted(r for r, _b in res.backups), sorted(pv.replaced))
        self.assertEqual((tree / f'Procedures/{K2}.py').read_bytes(), read_zip(zp)[f'Procedures/{K2}.py'])
        self.assertEqual(sorted(b for _r, b in P.imports(reg.path)[0]['backups']), sorted(b for _r, b in res.backups))
        # a second replacement gets the next number, and v01 is left alone
        (tree / f'Procedures/{K2}.py').write_text('# second OLD\n', encoding='utf-8')
        P.install(zp, tree, reg)
        self.assertEqual((tree / 'Backups/packages/Procedures' / f'{K2}_backup_v02.py').read_text(), '# second OLD\n')
        self.assertEqual(b1.read_text(), '# OLD launcher\n')

    def test_a_fix_package_ships_only_the_sidecar_and_the_named_file(self):
        zp = self.package(only=['drivers/keithley_2000.py'])
        members = read_zip(zp)
        self.assertEqual(set(members), {'manifest.json', f'Procedures/{K2}.procedure.json', 'drivers/keithley_2000.py'})
        man = json.loads(members['manifest.json'])
        self.assertIn(f'Procedures/{K2}.py', man['requires'])                                # the launcher is required, not shipped
        tree, reg = self.old_target()
        (tree / 'drivers/keithley_2000.py').write_text('# OLD driver\n', encoding='utf-8')
        pv = P.inspect(zp, tree, reg)
        self.assertTrue(pv.ok, pv.errors)
        self.assertEqual(pv.replaced, ['drivers/keithley_2000.py'])
        res = P.install(zp, tree, reg)
        self.assertEqual([r for r, _b in res.backups], ['drivers/keithley_2000.py'])
        self.assertEqual((tree / 'Backups/packages/drivers/keithley_2000_backup_v01.py').read_text(), '# OLD driver\n')
        self.assertEqual((tree / 'drivers/keithley_2000.py').read_bytes(), members['drivers/keithley_2000.py'])
        self.assertEqual((tree / f'Procedures/{K2}.py').read_text(), '# OLD launcher\n')       # not part of the package: untouched

    def test_a_failure_part_way_puts_everything_back_and_records_nothing(self):
        zp = self.package()
        tree, reg = self.old_target()
        before = self.tree_snapshot(tree)
        real, calls = P._atomic_write, []

        def flaky(dest, raw):
            calls.append(dest)
            if len(calls) == 2:
                raise OSError('disk full')
            return real(dest, raw)
        with mock.patch.object(P, '_atomic_write', flaky):
            with self.assertRaises(P.PackageError) as c:
                P.install(zp, tree, reg)
        self.assertIn('put back', str(c.exception))
        after = self.tree_snapshot(tree)
        self.assertEqual({k: v for k, v in after.items() if not k.startswith('Backups/')}, before)       # (the backups made first may remain)
        self.assertEqual(P.imports(reg.path), [])
        self.assertEqual([p for p in tree.rglob('.pkg_*')], [])

    def test_a_backup_that_cannot_be_made_stops_before_any_write(self):
        zp = self.package()
        tree, reg = self.old_target()
        before = self.tree_snapshot(tree)
        with mock.patch.object(P.shutil, 'copy2', side_effect=OSError('read only')):
            with self.assertRaises(P.PackageError) as c:
                P.install(zp, tree, reg)
        self.assertIn('backup', str(c.exception).lower())
        self.assertEqual(self.tree_snapshot(tree), before)

    def test_backups_use_the_next_free_number_even_with_gaps(self):
        tree = self.t / 'gap'
        d = tree / 'Backups/packages/specs'
        d.mkdir(parents=True)
        (d / 'x_backup_v01.json').write_text('1')
        (d / 'x_backup_v02.json').write_text('2')
        self.assertEqual(P.next_backup(tree, 'specs/x.json').name, 'x_backup_v03.json')


class VerifiedMarks(Base):
    def exported_with_mark(self):
        self.verify_in(self.src_reg, self.src)
        return self.package(with_verified_mark=True)

    def test_a_valid_mark_counts_when_the_installed_fingerprint_matches(self):
        zp = self.exported_with_mark()
        man = json.loads(read_zip(zp)['manifest.json'])
        self.assertEqual((man['verified']['who'], man['verified']['date']), ('Mike', '2026-10-20'))
        tree, reg = self.target()
        pv = P.inspect(zp, tree, reg)
        self.assertEqual(pv.mark_state, 'valid', pv.mark_detail)
        res = P.install(zp, tree, reg)
        self.assertTrue(res.mark_applied)
        proc = procscan.find(K2, tree)
        st = reg.status(V.make_entry(proc.name, proc.model, tree / proc.launcher, tree))
        self.assertEqual((st.kind, st.record.verified_by, st.record.verified_on), ('verified', 'Mike', '2026-10-20'))
        self.assertTrue(reg.lock_reason(proc_key=f'{K2}.py'))
        self.assertIn('package', reg.history(f'{K2}.py')[0]['note'].lower())

    def test_a_mark_does_not_count_when_a_shared_file_differs_here(self):
        zp = self.exported_with_mark()
        tree, reg = self.target()
        (tree / 'drivers/fluke_5560a.py').write_text((tree / 'drivers/fluke_5560a.py').read_text() + '\n# local edit\n')
        pv = P.inspect(zp, tree, reg)
        self.assertEqual(pv.mark_state, 'invalid')
        self.assertIn('not the ones that were verified', pv.mark_detail)
        res = P.install(zp, tree, reg)
        self.assertFalse(res.mark_applied)
        proc = procscan.find(K2, tree)
        self.assertEqual(reg.status(V.make_entry(proc.name, proc.model, tree / proc.launcher, tree)).kind, 'none')
        self.assertIn('invalid', P.imports(reg.path)[0]['mark'])

    def test_a_forged_or_incomplete_mark_is_ignored(self):
        zp = self.exported_with_mark()
        tree, reg = self.target()
        for change in ({'fingerprint': '0' * 64}, {'who': ''}, {'date': '2999-01-01'}, {'date': 'yesterday-ish'}):
            with self.subTest(change):
                z2 = self.t / f'forged{len(str(change))}{abs(hash(str(change))) % 999}.zip'
                z2.write_bytes(zp.read_bytes())

                def edit(m, change=change):
                    man = json.loads(m['manifest.json'])
                    man['verified'].update(change)
                    m['manifest.json'] = json.dumps(man).encode()
                rewrite_zip(z2, edit)
                pv = P.inspect(z2, tree, reg)
                self.assertTrue(pv.ok)
                self.assertEqual(pv.mark_state, 'invalid')

    def test_a_mark_does_not_count_where_the_model_has_saved_changes(self):
        zp = self.exported_with_mark()
        tree, reg = self.target()
        with mock.patch.object(reg, 'override_digests', return_value={'setting:x@model': 'abc'}):
            pv = P.inspect(zp, tree, reg)
        self.assertEqual(pv.mark_state, 'invalid')
        self.assertIn('saved procedure changes', pv.mark_detail)

    def test_no_mark_can_be_exported_for_an_unverified_or_changed_procedure(self):
        with self.assertRaises(P.PackageError) as c:
            self.package(with_verified_mark=True)
        self.assertIn('verified on hardware', str(c.exception))
        self.verify_in(self.src_reg, self.src)
        (self.src / 'drivers/keithley_2000.py').write_text('# edited after verification\n')
        with self.assertRaises(P.PackageError):
            self.package(with_verified_mark=True)

    def test_replacing_a_locked_procedure_unlocks_it_unless_the_mark_validates(self):
        # the installation has the procedure verified and locked (an older spec)
        tree, reg = self.target([K2], shared_for=())
        (tree / 'specs/keithley_2000_pv.json').write_text('{"old": true}')
        _rec, entry = self.verify_in(reg, tree)
        self.assertTrue(reg.lock_reason(proc_key=f'{K2}.py'))
        zp = self.package()                                                                  # a package WITHOUT a mark
        pv = P.inspect(zp, tree, reg)
        self.assertTrue(pv.locked_before and pv.will_unlock)
        self.assertTrue(any('VERIFIED ON HARDWARE' in w and 'UNLOCKED' in w.upper() for w in pv.warnings), pv.warnings)
        res = P.install(zp, tree, reg)
        self.assertTrue(res.unlocked and not res.mark_applied)
        self.assertEqual(reg.lock_reason(proc_key=f'{K2}.py'), '')                           # editable again
        st = reg.status(entry)
        self.assertNotEqual(st.kind, 'verified')
        hist = reg.history(f'{K2}.py')
        self.assertEqual([h['action'] for h in hist], ['verify', 'unlock'])
        self.assertEqual(hist[-1]['who'], P.IMPORT_WHO)
        self.assertIn('replaced by package', hist[-1]['reason'])
        self.assertEqual(P.imports(reg.path)[0]['unlocked'], 1)

    def test_replacing_a_locked_procedure_with_a_valid_mark_unlocks_then_locks_again(self):
        self.verify_in(self.src_reg, self.src, who='Dana', on_date='2026-10-21')
        zp = self.package(with_verified_mark=True)
        tree, reg = self.target([K2], shared_for=())
        (tree / 'specs/keithley_2000_pv.json').write_text('{"old": true}')
        self.verify_in(reg, tree)
        pv = P.inspect(zp, tree, reg)
        self.assertEqual(pv.mark_state, 'valid')
        res = P.install(zp, tree, reg)
        self.assertTrue(res.unlocked and res.mark_applied)
        self.assertEqual([h['action'] for h in reg.history(f'{K2}.py')], ['verify', 'unlock', 'verify'])
        rec = reg.record(f'{K2}.py')
        self.assertTrue(rec.locked)
        self.assertEqual((rec.verified_by, rec.verified_on), ('Dana', '2026-10-21'))

    def test_an_identical_package_leaves_a_locked_procedure_locked(self):
        zp = self.package()
        tree, reg = self.target()
        P.install(zp, tree, reg)
        _r, entry = self.verify_in(reg, tree)
        pv = P.inspect(zp, tree, reg)
        self.assertFalse(pv.will_unlock)
        res = P.install(zp, tree, reg)
        self.assertFalse(res.unlocked)
        self.assertEqual(reg.status(entry).kind, 'verified')

    def test_other_locked_procedures_that_use_a_replaced_shared_file_are_listed_and_show_changed(self):
        src = make_tree(self.t / 'src117b', [H117])
        (src / 'drivers/fluke_5560a.py').write_text((src / 'drivers/fluke_5560a.py').read_text() + '\n# newer calibrator driver\n')
        zp = P.build_package(H117, src, self.out, registry=V.Registry(self.t / 'x.sqlite3', base=src), extra_files=['drivers/fluke_5560a.py'])
        tree, reg = self.target([K2], shared_for=(H117,))
        self.assertTrue(procscan.find(K2, tree))
        _r, entry = self.verify_in(reg, tree)
        pv = P.inspect(zp, tree, reg)
        self.assertTrue(pv.ok, pv.errors)
        self.assertEqual([n for n, _c in pv.affected], ['Keithley 2000 Performance Verification'])
        self.assertIn('drivers/fluke_5560a.py', pv.replaced)
        P.install(zp, tree, reg)
        self.assertEqual(reg.status(entry).kind, 'changed')


class LibraryFolderSetting(Base):
    def test_default_empty_and_round_trip(self):
        path = self.t / 'cfg' / 'packages.json'
        self.assertEqual(P.get_library_dir(path), '')
        P.set_library_dir(str(self.t / 'lib'), path)
        self.assertEqual(P.get_library_dir(path), str(self.t / 'lib'))
        P.set_library_dir('', path)
        self.assertEqual(P.get_library_dir(path), '')

    def test_in_library_flag(self):
        zp = self.package()
        tree, reg = self.target()
        self.assertTrue(P.inspect(zp, tree, reg, library_dir=str(self.out)).in_library)
        pv = P.inspect(zp, tree, reg, library_dir=str(self.t / 'elsewhere'))
        self.assertIs(pv.in_library, False)
        self.assertTrue(pv.warnings[0].startswith('This file is NOT inside'))
        self.assertIsNone(P.inspect(zp, tree, reg).in_library)

    def test_settings_file_is_the_one_ui_settings_uses(self):
        self.assertEqual(P._settings_path().name, 'packages.json')
        self.assertEqual(P._settings_path().parent.name, '.calibration_suite')

    def test_bad_settings_file_reads_as_empty(self):
        bad = self.t / 'bad.json'
        bad.write_text('{nope')
        self.assertEqual(P.get_library_dir(bad), '')
        bad.write_text('[1,2]')
        self.assertEqual(P.get_library_dir(bad), '')


if __name__ == '__main__':
    unittest.main()
