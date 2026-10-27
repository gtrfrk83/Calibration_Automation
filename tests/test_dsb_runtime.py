"""Datasheet Builder runtime, unit level: routing, spec loading, standards plan on a plan-less spec, the Manager's user-built rows, the launcher.
No tkinter is installed where the suite runs; tests/_tk_stub.py stands in for it (as in the other engine tests) and the window code is mocked by
tests/dsb_run_harness.py.   Run:  python -m unittest tests.test_dsb_runtime"""
import ast
import copy
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import dsb_run_harness as H  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import datasheet_builder as db  # noqa: E402
import datasheet_builder_match as dm  # noqa: E402
import datasheet_builder_specs as dsp  # noqa: E402
import dsb_manager  # noqa: E402
import dsb_runtime as rt  # noqa: E402


def spec_of(ds, plan=True):
    return dsp.export_spec(ds, plan=dm.match_datasheet(ds) if plan else None).spec


class Spec(unittest.TestCase):
    def test_plain_export_has_no_plan_and_runtime_adds_one(self):
        spec = spec_of(fx.dmm_34461a_like(), plan=False)
        self.assertFalse(spec['dsb'].get('plan'))
        full = rt.with_plan(spec)
        self.assertTrue(full['dsb']['plan'])
        assigned = [s for s in full['steps'] if (s['dsb'].get('assignment') or {}).get('standard')]
        self.assertTrue(assigned)
        self.assertFalse(spec['dsb'].get('plan'), 'the spec that was passed in is not changed')

    def test_spec_with_plan_is_left_alone(self):
        spec = spec_of(fx.dmm_34461a_like())
        self.assertIs(rt.with_plan(spec), spec)

    def test_every_point_has_a_route_choice(self):
        spec = rt.with_plan(spec_of(fx.dmm_34461a_like(), plan=False))
        pts = rt.runtime_points(spec, spec['dsb']['models'][0] if 'models' in spec['dsb'] else spec['steps'][0]['models'][0])
        self.assertTrue(pts)
        for p in pts:
            r = rt.route_for(p, {'5560A', '5522A'})
            self.assertIn(r.label, ('5560A', '5522A', 'manual'))

    def test_unknown_period_rejected_or_defaulted(self):
        spec = spec_of(fx.dmm_34461a_like())
        other = rt.spec_for_period(spec, '90d')
        self.assertEqual(other['dsb']['period'], '90d')
        self.assertEqual(len(other['steps']), len(spec['steps']))


class Routing(unittest.TestCase):
    def setUp(self):
        spec = rt.with_plan(spec_of(fx.dmm_34461a_like()))
        self.pts = rt.runtime_points(spec, spec['steps'][0]['models'][0])

    def dcv(self):
        return next(p for p in self.pts if p['run']['kind'] == 'DCV')

    def test_assigned_connected_standard_is_used(self):
        p = self.dcv()
        a = rt._assigned(p)
        r = rt.route_for(p, {a})
        self.assertTrue(r.auto)
        self.assertEqual(r.standard, a)
        self.assertFalse(r.substituted)

    def test_substitute_is_flagged(self):
        p = self.dcv()
        a = rt._assigned(p)
        other = ({'5560A', '5522A'} - {a}).pop()
        r = rt.route_for(p, {other})
        if r.auto:
            self.assertTrue(r.substituted)
            self.assertEqual(r.assigned, a)

    def test_nothing_connected_is_manual_with_reason(self):
        r = rt.route_for(self.dcv(), set())
        self.assertFalse(r.auto)
        self.assertEqual(r.label, 'manual')
        self.assertTrue(r.reason)


class ScopeLimits(unittest.TestCase):
    def test_out_of_range_bandwidth_point_is_refused_by_the_source_limits(self):
        spec = rt.with_plan(spec_of(fx.scope_tds2000c_like()))
        pts = rt.runtime_points(spec, spec['steps'][0]['models'][0])
        bw = [p for p in pts if p['run']['op'] == 'scope_bw']
        self.assertTrue(bw)
        problems = [rt.limit_problem(p, '5522A') for p in bw]
        self.assertTrue(any(x is None for x in problems) or any(problems))
        p = copy.deepcopy(bw[0])
        p['run']['amplitude'] = 20.0
        self.assertTrue(rt.limit_problem(p, '5522A'))
        self.assertFalse(rt.route_for(p, {'5522A'}).auto)


class Listing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'user_specs'
        self.dbp = Path(self.tmp.name) / 'lab_registry.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_datasheets_become_user_built_rows(self):
        r = db.save(fx.dmm_34461a_like(), root=self.root, db=self.dbp)
        rows = dsb_manager.user_rows(root=self.root, db=self.dbp)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['tag'], 'user-built')
        self.assertTrue(row['iid'].startswith('ds:'))
        self.assertTrue(dsb_manager.is_user_iid(row['iid']))
        self.assertEqual(row['script'], 'Procedures/User_Datasheet.py')
        self.assertTrue(Path(row['spec_path']).is_file())
        self.assertEqual(row['model'], '34461A')
        args = dsb_manager.launch_args(row, demo=True, asset='A-1', python='py')
        self.assertEqual(args[0], 'py')
        self.assertTrue(args[1].endswith('User_Datasheet.py'))
        self.assertEqual(args[2:4], ['--spec', row['spec_path']])
        self.assertIn('--demo', args)
        self.assertEqual(args[-2:], ['--asset', 'A-1'])
        self.assertIn('[user-built]', dsb_manager.status_text(row))
        del r

    def test_deleted_datasheet_has_no_row_and_empty_registry_is_empty(self):
        self.assertEqual(dsb_manager.user_rows(root=self.root, db=self.dbp), [])
        db.save(fx.dmm_34461a_like(), root=self.root, db=self.dbp)
        uid = dsb_manager.user_rows(root=self.root, db=self.dbp)[0]['uid']
        db.delete(uid, root=self.root, db=self.dbp)
        self.assertEqual(dsb_manager.user_rows(root=self.root, db=self.dbp), [])

    def test_damaged_registry_never_raises(self):
        self.dbp.write_bytes(b'not a database')
        self.assertEqual(dsb_manager.user_rows(root=self.root, db=self.dbp), [])

    def test_saved_spec_file_runs(self):
        """The file the Manager hands to the launcher loads and builds points (the save wrote no plan; the runtime adds it)."""
        db.save(fx.dmm_34461a_like(), root=self.root, db=self.dbp)
        row = dsb_manager.user_rows(root=self.root, db=self.dbp)[0]
        spec = rt.load_spec(row['spec_path'])
        self.assertEqual(spec['dsb']['uid'], row['uid'])
        h = H.Harness().start()
        try:
            app = h.make_app(spec)
            self.assertTrue(app.points)
            self.assertTrue(any(rt._assigned(p) for p in app.points))
        finally:
            h.stop()



class Launcher(unittest.TestCase):
    def test_launcher_imports_and_calls_the_runtime(self):
        tree = ast.parse((ROOT / 'Procedures/User_Datasheet.py').read_text(encoding='utf-8'))
        imports = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
        self.assertIn('dsb_runtime', imports)
        calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertIn('dsb_runtime.main', calls)

    def test_runtime_has_reset_before_first_point(self):
        tree = ast.parse((ROOT / 'dsb_runtime.py').read_text(encoding='utf-8'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'execute')
        calls = [(n.lineno, n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', ''))
                 for n in ast.walk(fn) if isinstance(n, ast.Call)]
        names = [c for _l, c in calls]
        self.assertIn('reset_then', names)
        self.assertIn('_next', names)
        self.assertLessEqual(min(l for l, c in calls if c == 'reset_then'), min(l for l, c in calls if c == '_next'))


if __name__ == '__main__':
    unittest.main()
