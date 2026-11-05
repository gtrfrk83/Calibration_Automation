"""Standards from the run (standards_used.py + report_review_model.ReviewModel.apply_standards): the list, the observed capture, the assignment, the RSS of a second
standard, the bench profiles and - the regression the owner asked for - that a single-standard row prints EXACTLY what it printed before for the 34470A, handheld, 8846A,
dacq and 8808A engines.  Rows come from the same simulated-bench builders the review tests use; no window is opened.
Run:  python -m unittest tests.test_standards_used
"""
import json
import math
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'Procedures'))
from tests import _tk_stub as _boot  # noqa: E402
_boot.install()  # noqa: E402
import reprint_harness as R  # noqa: E402
import golden_engines as ge  # noqa: E402
import test_reprint_review as TR  # noqa: E402
import labregistry  # noqa: E402
import report_review_model as M  # noqa: E402
import standards_used as su  # noqa: E402
import uncertainty_budget as ub  # noqa: E402


def bare_app(App, points, n=12, **attrs):
    """An engine App with recorded results for a sample of its points (no window, no instrument): what certificate_rows_and_points reads."""
    app = object.__new__(App)
    app.asset, app.serial, app.status, app.root, app.demo = R.Var('A-100'), R.Var('SN-1'), R.Var(), mock.MagicMock(), False
    app.period = R.Var('1 year')
    for k, v in attrs.items():
        setattr(app, k, v)
    for p in ge.sample(points, ge._dmm_key, n):
        app.found[str(p['id'])] = dict(reading=p['nominal'], result='PASS', synthetic=False, timestamp=R.FIXED.isoformat(timespec='seconds'), data='As Found')
    return app


def engines():
    """name -> app, for the engines of the regression (handheld is built in HandheldRegression)."""
    out = {}
    app, _T = TR.truevolt_app()
    out['34470A'] = app
    import dacq_verification as D
    D.configure('34970A')
    out['dacq 34970A'] = bare_app(D.App, D.POINTS, cal_model=R.Var('Fluke 5560A'))
    import fluke8808a_verification as F
    F.configure('8808A')
    out['8808A'] = bare_app(F.App, F.POINTS, cal_model=R.Var('Fluke 5522A'))
    import Fluke_8846A_Verification as V
    out['8846A'] = bare_app(V.App, V.POINTS)
    return out


def printed(model):
    """Every cell the PDF would print for the review, row by row, plus the stored change list."""
    return [(r.spec.idx, r.reported_text, r.tar_text, r.tur_text, r.status, r.standard) for r in model.rows], model.changes()


def listed_for(model):
    """A list that contains the engine's own standard(s) and others (the 5560A, 5522A, 5520A, a 5790B as a measuring standard)."""
    return su.StandardsUsed([dict(model='5560A', asset='A-1'), dict(model='5522A', asset='A-2'), dict(model='5520A'), dict(model='5790B', role='measure')])


class Regression(unittest.TestCase):
    """Single-standard rows print exactly the same numbers with a list as without one (observed = the engine's standard, assumed, or the list absent)."""

    @classmethod
    def setUpClass(cls):
        cls.apps = engines()

    def check(self, app):
        specs, default = M.specs_for(app)
        plain = M.ReviewModel(specs, default, asset='A-100')
        want = printed(plain)
        # (1) a list, no capture at all: every row 'assumed'
        m1 = M.ReviewModel(specs, default, asset='A-100')
        m1.apply_standards(listed_for(m1), None)
        self.assertEqual(printed(m1), want)
        # (2) a list, and the run saw the engine's own standard on every point (what a real run shows): 'observed'
        obs = {r.spec.step: [r.spec.default_std] for r in plain.rows if r.spec.default_std}
        m2 = M.ReviewModel(specs, default, asset='A-100')
        m2.apply_standards(listed_for(m2), obs)
        self.assertEqual(printed(m2), want)
        self.assertEqual(m2.table(), plain.table())
        # (3) an empty list does nothing at all, and the stored record has no new keys
        m3 = M.ReviewModel(specs, default, asset='A-100')
        m3.apply_standards(su.StandardsUsed(), obs)
        self.assertEqual(m3.record(), plain.record())
        self.assertNotIn('standards_used', plain.record())
        return plain, m2

    def test_34470A(self):
        plain, m2 = self.check(self.apps['34470A'])
        free = [r for r in m2.rows if not r.spec.locked]
        self.assertTrue(free)
        self.assertTrue(all(r.use.basis == su.OBSERVED for r in free))

    def test_dacq(self):
        self.check(self.apps['dacq 34970A'])

    def test_8808A(self):
        self.check(self.apps['8808A'])

    def test_8846A(self):
        self.check(self.apps['8846A'])

    def test_untouched_rows_keep_the_engines_strings(self):
        for name, app in self.apps.items():
            specs, default = M.specs_for(app)
            m = M.ReviewModel(specs, default, asset='A-100')
            m.apply_standards(listed_for(m), {r.spec.step: [r.spec.default_std] for r in m.rows if r.spec.default_std})
            for r in m.rows:
                if not r.changed:
                    self.assertEqual(r.reported_text, r.spec.printed.get('Uncertainty', r.cur.unc_text), (name, r.spec.step))


class HandheldRegression(unittest.TestCase):
    def test_handheld(self):
        h = TR.H.Harness().start()
        self.addCleanup(h.stop)
        spec = TR.B.spec_of(TR.fx.dmm_34461a_like())
        spec['steps'] = spec['steps'][::7]
        app = h.make_app(spec, io=TR.B.cal_io())
        h.default_reading = TR.H.typed_nominal
        self.assertTrue(h.run_all())
        specs, default = M.specs_for(app)
        plain = M.ReviewModel(specs, default, asset='A-100')
        m = M.ReviewModel(specs, default, asset='A-100')
        m.apply_standards(listed_for(m), None)              # the handheld engines have no capture: every row is assumed
        self.assertEqual(printed(m), printed(plain))
        self.assertTrue(all(r.use.basis == su.ASSUMED for r in m.rows if r.use.primary is not None))


class Capture(unittest.TestCase):
    def test_the_command_log_records_which_instruments_a_point_touched_and_the_wire_is_unchanged(self):
        self.assertTrue(su.install())
        self.assertTrue(su.install())                                    # idempotent
        app, T = TR.truevolt_app(n=1)
        from drivers.simulated import make_dmm_bench

        def run(mark):
            bench, ft, dt = make_dmm_bench('34470A')
            io = T.IO('sim', 'sim', transports=(dt, ft))
            io.reset_at_start()
            a = object.__new__(T.App)
            a.io = io
            pts = [p for p in T.POINTS if p.get('source') != 'none' and p['kind'] == 'DCV'][:3]
            for p in pts:
                if mark:
                    su.mark_point(a, p)
                dt.terminals = 'REAR' if p.get('terminal') == 'REAR' else 'FRON'
                with mock.patch.object(T.time, 'sleep', lambda s: None):
                    io.measure(p)
            return a, pts, [e[1:] for e in io.log.entries]

        a, pts, marked = run(True)
        _, _, plain = run(False)
        self.assertEqual(marked, plain)                                  # nothing is added to the wire or to the log text
        obs = su.observed_for(a)
        self.assertEqual(len(pts), 3)
        self.assertTrue(obs)
        for p in pts:
            self.assertIn('5560A', obs[str(p['id'])])
            self.assertNotIn(None, obs[str(p['id'])])                   # the meter under test is not a standard
        self.assertIsNone(su.observed_for(object.__new__(T.App)))         # no capture: None, not {}
        import drivers
        self.assertIsNone(su.observed_for(types.SimpleNamespace(log=drivers.CommandLog())))      # a log nothing was marked on: no capture either

    def test_model_of_label(self):
        self.assertEqual(su.model_of_label('5560A'), '5560A')
        self.assertEqual(su.model_of_label('Fluke5790B'), '5790B')
        self.assertEqual(su.model_of_label('Keysight 3458A'), '3458A')
        self.assertIsNone(su.model_of_label('34470A'))
        self.assertIsNone(su.model_of_label(''))


class Assign(unittest.TestCase):
    def covers(self, ok):
        return lambda s: f'row of {s.model}' if s.model in ok else ''

    def test_observed_wins_and_the_tie_break_is_shown(self):
        L = su.StandardsUsed([dict(model='5560A', asset='1'), dict(model='5522A', asset='2'), dict(model='5522A', asset='3')])
        a = su.assign(L, ['5522A'], self.covers({'5560A', '5522A'}))
        self.assertEqual((a.primary.model, a.primary.asset, a.basis), ('5522A', '2', su.OBSERVED))
        self.assertIn('first listed', a.tie_break)
        self.assertIn('5560A', a.tie_break)
        self.assertIn('observed', a.why)

    def test_assumed_when_nothing_was_seen_first_listed_that_covers(self):
        L = su.StandardsUsed([dict(model='5560A'), dict(model='5522A')])
        a = su.assign(L, None, self.covers({'5522A'}))
        self.assertEqual((a.primary.model, a.basis), ('5522A', su.ASSUMED))
        self.assertIn('no capture', a.why)
        b = su.assign(L, [], self.covers({'5560A', '5522A'}))
        self.assertEqual((b.primary.model, b.basis), ('5560A', su.ASSUMED))
        self.assertIn('first listed', b.tie_break)

    def test_a_second_standard_is_only_ever_observed(self):
        L = su.StandardsUsed([dict(model='5560A'), dict(model='5790B', role='measure')])
        cov = self.covers({'5560A', '5790B'})
        self.assertIsNone(su.assign(L, None, cov).second)
        self.assertIsNone(su.assign(L, [], cov).second)
        a = su.assign(L, ['5560A', '5790B'], cov)
        self.assertEqual((a.primary.model, a.second.model), ('5560A', '5790B'))

    def test_the_unit_under_test_is_never_a_standard(self):
        L = su.StandardsUsed([dict(model='34461A', role='measure'), dict(model='5560A')])
        a = su.assign(L, ['34461A', '5560A'], self.covers({'34461A', '5560A'}), exclude=('34461A',))
        self.assertEqual(a.primary.model, '5560A')
        self.assertIsNone(a.second)

    def test_uut_asset_number_decides_when_entered(self):
        L = su.StandardsUsed([dict(model='34461A', asset='A-100', role='measure'), dict(model='34461A', asset='A-200', role='measure'), dict(model='5560A')])
        cov = self.covers({'34461A', '5560A'})
        seen = ['5560A', '34461A']
        # same model, different asset: still a standard
        a = su.assign(L, seen, cov, exclude=('34461A',), uut_asset='A-100')
        self.assertEqual((a.primary.model, a.second.model, a.second.asset), ('5560A', '34461A', 'A-200'))
        # same asset: excluded (and not offered as a candidate either)
        b = su.assign(L, seen, cov, exclude=('34461A',), uut_asset='A-200')
        self.assertEqual(b.second.asset, 'A-100')
        only = su.StandardsUsed([dict(model='34461A', asset='A-100', role='measure'), dict(model='5560A')])
        c = su.assign(only, seen, cov, exclude=('34461A',), uut_asset='a-100')          # case-insensitive
        self.assertIsNone(c.second)
        self.assertNotIn('34461A', [x.model for x in c.candidates])
        # a listed entry with no asset is not the UUT when the UUT asset is known
        d = su.assign(su.StandardsUsed([dict(model='34461A', role='measure'), dict(model='5560A')]), seen, cov, exclude=('34461A',), uut_asset='A-100')
        self.assertEqual(d.second.model, '34461A')

    def test_no_uut_asset_falls_back_to_the_model_rule(self):
        L = su.StandardsUsed([dict(model='34461A', asset='A-200', role='measure'), dict(model='5560A')])
        a = su.assign(L, ['5560A', '34461A'], self.covers({'34461A', '5560A'}), exclude=('34461A',), uut_asset='')
        self.assertIsNone(a.second)
        self.assertEqual(a.primary.model, '5560A')

    def test_the_review_passes_the_uut_asset_through(self):
        app, _T = TR.truevolt_app()
        specs, default = M.specs_for(app)
        L = su.StandardsUsed([dict(model='5560A', asset='A-1'), dict(model='5790B', asset='A-5', role='measure')])
        obs = {r.spec.step: ['5560A', '5790B'] for r in M.ReviewModel(specs, default).rows}
        m = M.ReviewModel(specs, default)
        m.apply_standards(L, obs, False, ('5790B',), 'A-5')                 # the 5790B IS the unit under test
        self.assertFalse([r for r in m.rows if r.cur.second])
        m2 = M.ReviewModel(specs, default)
        m2.apply_standards(L, obs, False, ('5790B',), 'A-999')              # a different instrument of that model
        self.assertTrue([r for r in m2.rows if r.cur.second == '5790B'])
        m2.reset()                                                          # reset re-applies with the same UUT asset
        self.assertTrue([r for r in m2.rows if r.cur.second == '5790B'])

    def test_gap(self):
        a = su.assign(su.StandardsUsed([dict(model='5560A')]), ['5560A'], self.covers(set()))
        self.assertTrue(a.gap)
        self.assertIsNone(a.primary)

    def test_demo_is_marked(self):
        a = su.assign(su.StandardsUsed([dict(model='5560A')]), ['5560A'], self.covers({'5560A'}))
        a.demo = True
        self.assertTrue(a.as_dict()['why'].startswith('SIMULATED RUN'))


class TwoStandards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, _T = TR.truevolt_app()
        cls.specs, cls.default = M.specs_for(cls.app)

    def spec(self, kind, ac=False):
        return next(s for s in self.specs if not s.locked and s.q['kind'] == kind and s.q['nominal'] > 0 and bool(s.q.get('frequency')) == ac)

    def test_rss_by_hand(self):
        s = self.spec('DCV')
        b1 = ub.build('DCV', s.q['nominal'], s.q['unit'], standard='5560A')
        b2 = ub.build('DCV', s.q['nominal'], s.q['unit'], standard='5790B', direction='input')
        self.assertIsNotNone(b2.hit)
        want = 2 * math.sqrt(b1.combined ** 2 + b2.combined ** 2)
        e = M.evaluate(s, '5560A', '5790B')
        self.assertAlmostEqual(e.budget, want, delta=want * 1e-9)
        self.assertEqual(e.second, '5790B')
        self.assertGreater(e.budget, b1.emu)
        self.assertGreaterEqual(e.reported, e.cmc * (1 - 1e-12))          # the scope floor is the first standard's, never lowered
        import uncertainty
        self.assertEqual(e.unc_text, uncertainty.format_value(uncertainty.round_up(max(want, b1.cmc)), s.q['unit']))

    def test_rows_follow_the_observed_second_standard(self):
        m = M.ReviewModel(self.specs, self.default, asset='A-100')
        m.apply_standards(listed_for(m), {r.spec.step: ['5560A', '5790B'] for r in m.rows})
        twos = [r for r in m.rows if r.cur.second]
        self.assertTrue(twos)
        for r in twos:
            self.assertEqual(r.status, M.CHANGED)
        ch = [c for c in m.changes() if c.get('second_standard')]
        self.assertEqual(len(ch), len(twos))
        self.assertTrue(all(c['combined'] == 'RSS' for c in ch))
        # a second standard whose sheet has no row at the point adds nothing and the row says so
        for r in m.rows:
            if r.use is not None and r.use.second is None and r.spec.q and not r.spec.locked and not r.cur.second:
                self.assertIsNone(r.second)

    def test_a_different_observed_standard_moves_the_row(self):
        m = M.ReviewModel(self.specs, self.default, asset='A-100')
        m.apply_standards(listed_for(m), {r.spec.step: ['5522A'] for r in m.rows})
        moved = [r for r in m.rows if not r.spec.locked and r.standard == '5522A']
        self.assertTrue(moved)
        self.assertTrue(all(r.status == M.CHANGED and r.use.basis == su.OBSERVED for r in moved))

    def test_reset_applies_the_run_again_and_a_person_pick_wins(self):
        m = M.ReviewModel(self.specs, self.default, asset='A-100')
        m.apply_standards(listed_for(m), {r.spec.step: ['5560A', '5790B'] for r in m.rows})
        idx = next(r.spec.idx for r in m.rows if r.cur.second)
        self.assertTrue(m.set_standard(idx, '5522A'))
        self.assertIsNone(m.rows[idx].cur.second)                       # the person's pick is a single standard
        m.reset()
        self.assertEqual(m.rows[idx].cur.second, '5790B')


class GapsAndRecord(unittest.TestCase):
    def test_gaps_listed_and_record_json_round_trips(self):
        app, _T = TR.truevolt_app()
        specs, default = M.specs_for(app)
        m = M.ReviewModel(specs, default, asset='A-100')
        m.apply_standards(su.StandardsUsed([dict(model='8902A', role='measure')]), None)         # a list no multimeter point is covered by
        gaps = m.coverage_gaps()
        self.assertEqual(len(gaps), sum(1 for r in m.rows if not r.spec.locked))
        rec = json.loads(json.dumps(M.review_block([m], by='T', when='2026-01-01T00:00:00')))
        r0 = rec['reviews'][0]
        self.assertEqual(r0['standards_used']['list'][0]['model'], '8902A')
        self.assertEqual(len(r0['coverage_gaps']), len(gaps))
        self.assertEqual(len(r0['assignments']), len(m.rows))
        self.assertEqual(su.StandardsUsed.from_record(r0['standards_used']).models(), ['8902A'])

    def test_coverage_text_shows_the_sheet_row_band_and_confidence(self):
        q = dict(kind='ACV', nominal=1.0, unit='V', frequency=1000.0, range=None)
        t = M.coverage_text(q, su.StandardUse('5560A'))
        self.assertIn('5560A', t)
        self.assertIn('Hz', t)
        self.assertIn('confidence', t)
        self.assertEqual(M.coverage_text(dict(q, kind='NOPE'), su.StandardUse('5560A')), '')


class Sheets(unittest.TestCase):
    def test_every_candidate_model_has_a_sheet_row_in_the_direction_of_its_role(self):
        import specmanager as sm
        with tempfile.TemporaryDirectory() as d, mock.patch.object(labregistry, 'DB', Path(d) / 'lab_registry.sqlite3'):
            sm.seed()
            for model, role in su.CANDIDATE_MODELS.items():
                std = sm.standard(model)
                self.assertIsNotNone(std, model)
                dirs = {r['direction'] for r in std.rows}
                self.assertIn(su.DIRECTION[role], dirs, f'{model} has no {su.DIRECTION[role]} rows')


class Profiles(unittest.TestCase):
    def test_profiles_live_in_lab_registry_only(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(labregistry, 'DB', Path(d) / 'lab_registry.sqlite3'), \
                mock.patch.object(labregistry, 'MAIN_DB', Path(d) / 'calibration_procedures.sqlite3'):
            L = su.StandardsUsed([dict(model='5560A', asset='A-77'), dict(model='5790B', asset='A-78', role='measure')])
            self.assertTrue(su.save_profile('Bench 3', L, note='DMM bench'))
            self.assertEqual(su.profile_names(), ['Bench 3'])
            back = su.load_profile('Bench 3')
            self.assertEqual([x.as_dict() for x in back], [x.as_dict() for x in L])
            self.assertEqual(back.profile, 'Bench 3')
            self.assertTrue(su.save_profile('Bench 3', su.StandardsUsed([dict(model='5522A')])))      # replaces
            self.assertEqual(su.load_profile('Bench 3').models(), ['5522A'])
            self.assertIsNone(su.load_profile('missing'))
            self.assertTrue(su.delete_profile('Bench 3'))
            self.assertEqual(su.profile_names(), [])
            self.assertFalse((Path(d) / 'calibration_procedures.sqlite3').exists())                  # the Manager's database is never opened
            con = sqlite3.connect(str(Path(d) / 'lab_registry.sqlite3'))
            self.assertIn('bench_profiles', {r[0] for r in con.execute("select name from sqlite_master")})
            con.close()

    def test_a_demo_registry_is_never_written(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(labregistry, 'DB', Path(d) / labregistry.DEMO_DB_NAME):
            self.assertFalse(su.save_profile('x', su.StandardsUsed([dict(model='5560A')])))



class WhyText(unittest.TestCase):
    def test_why_text_names_basis_spec_row_tie_break_and_gaps(self):
        app, _T = TR.truevolt_app()
        specs, default = M.specs_for(app)
        m = M.ReviewModel(specs, default, asset='A-100')
        m.apply_standards(listed_for(m), {r.spec.step: ['5560A', '5790B'] for r in m.rows})
        r = next(r for r in m.rows if r.cur.second)
        t = M.why_text(m, r.spec.idx)
        for want in ('OBSERVED', '5790B', 'RSS', 'spec row', 'confidence', 'Coverage gaps: 0'):
            self.assertIn(want, t)
        m.apply_standards(su.StandardsUsed([dict(model='8902A', role='measure')]), None)
        self.assertIn('Coverage gaps:', M.why_text(m, None))
        self.assertNotIn('Coverage gaps: 0', M.why_text(m, None))



class NoFingerprintedFileIsEdited(unittest.TestCase):
    def test_capture_does_not_touch_the_files_71_verified_procedures_fingerprint(self):
        """Editing drivers/transport.py or manual_override.py would flip verified procedures to 'Changed since verification'; the capture wraps them at run time."""
        import subprocess
        out = subprocess.run(['git', 'diff', '--name-only', 'origin/main', 'HEAD'], capture_output=True, text=True, cwd=str(ROOT))
        if out.returncode:
            self.skipTest('no git history here')
        changed = set(out.stdout.split())
        side = ' '.join(p.read_text(encoding='utf-8') for p in (ROOT / 'Procedures').glob('*.procedure.json'))
        for f in sorted(changed):
            if f.endswith('.py') and not f.startswith('tests/'):
                self.assertNotIn(f'"{f}"', side, f'{f} is in a verified procedure fingerprint')


class OfferedStandards(unittest.TestCase):
    """The Standard drop-down also offers 5700A / 33250A / 96270A where their sheet covers the point (owner decision); today's numbers do not move."""

    def test_new_sources_are_offered_only_where_the_sheet_covers_and_the_old_order_is_kept(self):
        self.assertEqual(M.SOURCE_STANDARDS[:3], ('5560A', '5522A', '5520A'))
        self.assertEqual(M.SOURCE_STANDARDS[3:], ('5700A', '33250A', '96270A'))
        app, _T = TR.truevolt_app(n=40)
        specs, default = M.specs_for(app)
        seen_new = set()
        for s in specs:
            if s.locked:
                continue
            opts = M.offered_standards(s)
            self.assertEqual([o for o in opts if o in ('5560A', '5522A', '5520A')], [o for o in ('5560A', '5522A', '5520A') if o in opts])
            self.assertIn(s.default_std, opts)
            for o in opts:
                if o in ('5700A', '33250A', '96270A'):
                    seen_new.add(o)
                    import uncertainty_budget as ub
                    b = ub.build(s.q['kind'], s.q['nominal'], M._unit_of(s.q), standard=o, frequency=s.q.get('frequency'), scope=M.scope(), range_value=s.q.get('range'))
                    self.assertIsNotNone(b.hit, (o, s.description))           # offered only where the sheet has a row
                    e = M.evaluate(s, o)
                    if e.cmc is not None and e.reported is not None:
                        self.assertGreaterEqual(e.reported, e.cmc * (1 - 1e-12))
        self.assertIn('5700A', seen_new)

    def test_default_rows_print_the_same_with_the_longer_list(self):
        for app in (TR.truevolt_app()[0],):
            specs, default = M.specs_for(app)
            m = M.ReviewModel(specs, default, asset='A-100')
            for r in m.rows:
                if not r.changed:
                    self.assertEqual(r.reported_text, r.spec.printed.get('Uncertainty', r.cur.unc_text))


if __name__ == '__main__':
    unittest.main()
