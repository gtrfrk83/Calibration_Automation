"""Review window model (report_review_model.py) and the report path it feeds (report_pdf.apply_uncertainty_review, report snapshot, Regenerate PDF).

Rows come from real runs on the simulated benches: the Truevolt 34470A engine (real IO.measure against the simulated DMM + 5560A) and the handheld /
user-datasheet engine (handheld_dmm.App through dsb_runtime.DsbApp on the simulated calibrators).  No tkinter window is opened here (the real window is
checked by tests/real_tk_review.py); File name sorts after test_beta on purpose (reprint_harness installs tests/_tk_stub.py).
Run:  python -m unittest tests.test_reprint_review
"""
import json
import math
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import reprint_harness as R  # noqa: E402
import dsb_run_harness as H  # noqa: E402
import dsb_fixtures as fx  # noqa: E402
import test_dsb_runtime_bench as B  # noqa: E402
import labregistry  # noqa: E402
import report_dialog  # noqa: E402
import report_pdf  # noqa: E402
import report_review_model as M  # noqa: E402
import report_snapshot as rs  # noqa: E402
import tartur_wiring  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

try:
    import reportlab  # noqa: F401
    import pypdf  # noqa: F401
    HAVE = subprocess.run(['pdftotext', '-v'], capture_output=True).returncode in (0, 99)
except Exception:
    HAVE = False


def truevolt_app(demo=False, n=14):
    """The Truevolt 34470A engine after a (sampled) real run on the simulated bench, exactly as reprint_harness.truevolt_export, without exporting."""
    import golden_engines as ge
    import truevolt_verification as T
    from drivers.simulated import make_dmm_bench
    T.configure('34470A')
    bench, ft, dt = make_dmm_bench('34470A')
    io = T.IO('sim', 'sim', transports=(dt, ft))
    io.reset_at_start()
    app = object.__new__(T.App)
    app.asset, app.serial, app.status, app.root, app.demo = R.Var('A-100'), R.Var('SN-1'), R.Var(), mock.MagicMock(), demo
    app.period = R.Var('1 year')
    for p in ge.sample(T.POINTS, ge._dmm_key, n):
        dt.terminals = 'REAR' if p.get('terminal') == 'REAR' else 'FRON'
        with mock.patch.object(T.time, 'sleep', lambda s: None):
            reading = io.measure(p)
        app.found[str(p['id'])] = dict(reading=reading, result='PASS' if abs(reading - p['nominal']) <= p['error'] else 'FAIL', synthetic=demo,
                                       timestamp=R.FIXED.isoformat(timespec='seconds'), data='As Found')
    return app, T


def export(app, mod, out, details):
    with mock.patch.object(report_dialog, 'ask_details', lambda *a, **k: dict(details)), \
            mock.patch.object(mod.filedialog, 'asksaveasfilename', lambda **k: str(out)):
        app.export_pdf()


def regenerate(rid, out):
    return rs.regenerate(rid, choose_path=lambda name, original: str(out), confirm_overwrite=lambda p, o: False)


def hand_budget(kind, nominal, unit, standard, frequency=None):
    """The method written out by hand from the standard's published sheet row: u = limit / divisor, + resolution / sqrt(12), k = 2, floored at the CMC,
    rounded UP to 2 figures.  Returns (emu, cmc, reported)."""
    import specmanager as sm
    import uncertainty
    std = sm.standard(standard)
    hit = std.lookup(kind, nominal, frequency=frequency, direction='output')
    div, _why = std.divisor()
    u2 = (hit.limit / div) ** 2
    res, _src = std.resolution(hit)
    if res:
        u2 += (res / math.sqrt(12)) ** 2
    emu = 2.0 * math.sqrt(u2)
    cmc = uncertainty.load().dmm(kind, nominal, None, frequency)
    top = max(emu, cmc or 0.0)
    step = 10 ** (math.floor(math.log10(top)) - 1)
    return emu, cmc, math.ceil(round(top / step, 9)) * step


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class Model(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.T = truevolt_app()
        cls.specs, cls.default = M.specs_for(cls.app)
        cls.rows, cls.pts = cls.app.certificate_rows_and_points()

    def test_one_spec_per_report_row_and_default(self):
        self.assertEqual(len(self.specs), len(self.rows))
        self.assertEqual(self.default, '5560A')
        self.assertTrue(any(not s.locked for s in self.specs))

    def test_untouched_rows_equal_what_the_engine_printed(self):
        """The model's recalculation with the engine's own standard reproduces the printed Uncertainty and TUR of every changeable row."""
        for s, row, p in zip(self.specs, self.rows, self.pts):
            if s.locked:
                continue
            e = M.evaluate(s, s.default_std)
            self.assertEqual(e.unc_text, row['Uncertainty'], (s.step, s.description))
            self.assertEqual(e.tur, tartur_wiring.point_fields(p, '5560A')['TUR'], (s.step, s.description))

    def test_standard_change_recalculates_by_hand(self):
        s = next(x for x in self.specs if not x.locked and x.q['kind'] == 'DCV' and x.q['nominal'] > 0 and not x.q.get('frequency'))
        model = M.ReviewModel([s], '5560A', asset='A-100')
        self.assertTrue(model.set_standard(0, '5522A'))
        row = model.rows[0]
        emu, cmc, reported = hand_budget('DCV', s.q['nominal'], s.q['unit'], '5522A')
        self.assertAlmostEqual(row.cur.budget, emu, delta=emu * 1e-9)
        self.assertAlmostEqual(row.cur.cmc, cmc, delta=cmc * 1e-9)
        self.assertAlmostEqual(row.cur.reported, reported, delta=reported * 1e-9)
        self.assertGreaterEqual(row.cur.reported, row.cur.cmc)
        self.assertEqual(row.status, M.CHANGED)
        import uncertainty
        self.assertEqual(row.cur.unc_text, uncertainty.format_value(reported, s.q['unit']))
        self.assertEqual(model.changes()[0]['original_standard'], '5560A')
        # TUR = tolerance / reported
        tol = (s.high - s.low) / 2
        import tartur
        self.assertEqual(row.cur.tur, tartur.format_ratio(tol / reported))

    def test_reported_never_below_scope_minimum_for_any_row_and_standard(self):
        n = 0
        for s in self.specs:
            if s.locked:
                continue
            for std in M.offered_standards(s):
                e = M.evaluate(s, std)
                if e.cmc is not None and e.reported is not None:
                    self.assertGreaterEqual(e.reported, e.cmc * (1 - 1e-12), (s.step, std))
                    n += 1
        self.assertGreater(n, 5)

    def test_locked_rows_cannot_change(self):
        model = M.ReviewModel(self.specs, self.default, asset='A-100')
        locked = [i for i, r in enumerate(model.rows) if r.spec.locked]
        if locked:
            self.assertFalse(model.set_standard(locked[0], '5522A'))
        freq = [i for i, r in enumerate(model.rows) if r.spec.q.get('kind') == 'FREQ']
        for i in freq:
            self.assertTrue(model.rows[i].spec.locked)
            self.assertFalse(model.set_standard(i, '5522A'))

    def test_bulk_set_default_reset_and_filters(self):
        model = M.ReviewModel(self.specs, self.default, asset='A-100')
        free = [i for i, r in enumerate(model.rows) if not r.spec.locked]
        n = model.set_standard_many(free[:4], '5522A')
        self.assertEqual(n, len([i for i in free[:4] if '5522A' in model.options(i)]))
        self.assertEqual(model.counts()['changed'], n)
        self.assertEqual(len(model.visible('Changed by me')), n)
        model.reset()
        self.assertEqual(model.counts()['changed'], 0)
        model.set_default('5522A')                                              # the run default moves every row without its own choice
        moved = [r for r in model.rows if r.changed]
        self.assertTrue(moved)
        self.assertTrue(all(r.standard == '5522A' for r in moved))
        model.reset()
        self.assertEqual(model.default_std, '5560A')
        c = model.counts()
        self.assertEqual(c['all'], len(self.specs))
        self.assertEqual(len(model.visible('Needs attention')), c['attention'])

    def test_record_is_json_clean(self):
        model = M.ReviewModel(self.specs, self.default, asset='A-100')
        free = [i for i, r in enumerate(model.rows) if not r.spec.locked]
        model.set_standard_many(free[:3], '5522A')
        text = json.dumps(M.review_block([model]), allow_nan=False)
        self.assertIn('original_standard', text)


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class ReportPath(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        ctx = R.registry()
        self.db = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def review_details(self, app, count=3, standard='5522A', show=None):
        specs, default = M.specs_for(app)
        model = M.ReviewModel(specs, default, asset=app.asset.get())
        free = [i for i, r in enumerate(model.rows) if not r.spec.locked and standard in model.options(i)]
        picked = [i for i in free if model.rows[i].cur.unc_text and model.rows[i].cur.status != M.NOT_IN_SCOPE][:count]
        for i in picked:
            self.assertTrue(model.set_standard(i, standard))
        d = dict(R.DETAILS, uncertainty_review=M.review_block([model]))
        if show is not None:
            d['show_tar_tur'] = show
        return d, model, picked

    def test_change_prints_persists_and_regenerates(self):
        app, T = truevolt_app()
        base = self.dir / 'base.pdf'
        export(app, T, base, R.DETAILS)
        rows_before = app.certificate_rows()
        details, model, picked = self.review_details(app, show=report_pdf.TarTur(True, True))
        out = self.dir / 'changed.pdf'
        export(app, T, out, details)
        rid = R.last_run_id('A-100')
        snap = rs.load(rid)
        self.assertEqual(snap.status, rs.OK)
        stored = snap.data['rows']
        changes = {c['idx']: c for c in model.changes()}
        self.assertTrue(changes)
        for i, row in enumerate(stored):
            if i in changes:
                self.assertEqual(row['Uncertainty'], changes[i]['uncertainty'])
                self.assertEqual(row['TUR'], changes[i]['tur'])
            else:                                                          # a row nobody touched is exactly what the engine built (TAR / TUR from its own wiring)
                self.assertEqual(row['Uncertainty'], rows_before[i]['Uncertainty'])
        self.assertTrue(any(stored[i]['Uncertainty'] != rows_before[i]['Uncertainty'] for i in changes), 'a 5522A budget differs from the 5560A one somewhere')
        self.assertEqual(snap.data['details']['uncertainty_review']['reviews'][0]['changed'], len(changes))
        again = self.dir / 'again.pdf'
        res = regenerate(rid, again)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(R.differences(out, again, None), [], 'Regenerate PDF reprints the changed standard unchanged')
        self.assertNotEqual(R.pdf_text(out), R.pdf_text(base))

    def test_no_change_gives_the_same_pdf_as_before(self):
        app, T = truevolt_app()
        a, b = self.dir / 'a.pdf', self.dir / 'b.pdf'
        export(app, T, a, R.DETAILS)
        specs, default = M.specs_for(app)
        model = M.ReviewModel(specs, default, asset='A-100')
        export(app, T, b, dict(R.DETAILS, uncertainty_review=M.review_block([model])))
        self.assertEqual(R.differences(a, b, None), [])

    def test_mismatched_index_is_ignored(self):
        rows = [{'Description': 'x', 'Nominal': '1 V', 'Uncertainty': 'a', 'Section': ''}, {'Description': 'y', 'Nominal': '2 V', 'Uncertainty': 'b', 'Section': ''}]
        block = {'reviews': [{'asset': 'A-1', 'changes': [dict(idx=0, description='y', nominal='2 V', uncertainty='ZZ', tar='', tur=''),
                                                           dict(idx=1, description='y', nominal='2 V', uncertainty='NEW', tar='', tur=''),
                                                           dict(idx=9, description='y', nominal='2 V', uncertainty='ZZ')]}]}
        out = report_pdf.apply_uncertainty_review(rows, {'uncertainty_review': block}, [('Instrument ID', 'A-1')])
        self.assertEqual([r['Uncertainty'] for r in out], ['a', 'NEW'])
        same = report_pdf.apply_uncertainty_review(rows, {'uncertainty_review': block}, [('Instrument ID', 'OTHER')])
        self.assertEqual([r['Uncertainty'] for r in same], ['a', 'b'])
        self.assertEqual(rows[1]['Uncertainty'], 'b', 'the engine rows are not modified in place')

    def test_demo_report_is_marked_and_not_recorded(self):
        app, T = truevolt_app(demo=True)
        details, model, picked = self.review_details(app)
        out = self.dir / 'demo.pdf'
        export(app, T, out, details)
        text = R.pdf_text(out)
        self.assertIn('NOT CALIBRATION EVIDENCE', text)
        self.assertIsNone(R.last_run_id('A-100'))

    def test_old_snapshot_without_review_still_regenerates(self):
        app, T = truevolt_app()
        out = self.dir / 'o.pdf'
        export(app, T, out, R.DETAILS)
        rid = R.last_run_id('A-100')
        self.assertNotIn('uncertainty_review', rs.load(rid).data['details'])
        self.assertTrue(regenerate(rid, self.dir / 'o2.pdf').ok)


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class HandheldModel(unittest.TestCase):
    def setUp(self):
        self.h = H.Harness().start()
        self.addCleanup(self.h.stop)
        spec = B.spec_of(fx.dmm_34461a_like())
        spec['steps'] = spec['steps'][::7]
        self.app = self.h.make_app(spec, io=B.cal_io())
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())

    def test_handheld_rows_match_the_engine(self):
        specs, default = M.specs_for(self.app)
        rows, pts = self.app.certificate_rows_and_points()
        self.assertEqual(len(specs), len(rows))
        self.assertIn(default, ('5560A', '5522A', '5520A', None))
        checked = 0
        for s, row, p in zip(specs, rows, pts):
            if s.locked:
                continue
            e = M.evaluate(s, s.default_std)
            self.assertEqual(e.unc_text, row['Uncertainty'], (s.step, s.description))
            self.app._row_std = self.app.standard_of(p, self.app._record_for(p)) if hasattr(self.app, 'standard_of') else None
            try:
                want = self.app.certificate_fields(p)
            finally:
                self.app._row_std = None
            if want.get('TUR'):
                self.assertEqual(e.tur, want['TUR'], (s.step, s.description))
            checked += 1
        self.assertGreater(checked, 3)

    def test_handheld_standard_change_and_floor(self):
        specs, default = M.specs_for(self.app)
        model = M.ReviewModel(specs, default, asset='A-100')
        free = [i for i, r in enumerate(model.rows) if not r.spec.locked]
        self.assertTrue(free)
        for i in free:
            for std in model.options(i):
                e = M.evaluate(model.rows[i].spec, std)
                if e.cmc is not None and e.reported is not None:
                    self.assertGreaterEqual(e.reported, e.cmc * (1 - 1e-12))
        frequency = [r for r in model.rows if r.spec.q.get('kind') == 'FREQ']
        for r in frequency:
            self.assertTrue(r.spec.locked)


def oos_spec(idx=0, nominal=1000.0, tol=1.0):
    """ACV 1000 V at 10 Hz: the 5560A sheet describes it, the lab scope does not (status 'Not in scope')."""
    q = dict(kind='ACV', nominal=nominal, unit='V', frequency=10, range=None)
    return M.PointSpec(idx, '9-9', 'AC volts', 'AC 1000 V range', '1000 V @ 10 Hz', q, q, nominal - tol, nominal + tol, 'V', '5560A',
                       printed=dict(Uncertainty='760 mV', TAR='', TUR='1.3:1'))


class Manual(unittest.TestCase):
    def test_parse_units_and_bare_number(self):
        P = M.parse_uncertainty
        self.assertEqual(P('3.5 mV', 'V')[0], 0.0035)
        self.assertEqual(P('3.5mV', 'V')[0], 0.0035)
        self.assertEqual(P('2 \u00b5V', 'V')[0], 2e-6)
        self.assertEqual(P('2 uV', 'V')[0], 2e-6)
        self.assertEqual(P('1.2e-3 V', 'V')[0], 0.0012)
        self.assertEqual(P('0.5 mohm', 'ohm')[0], 0.0005)
        self.assertEqual(P('1.5 kOhm', 'ohm')[0], 1500.0)
        self.assertEqual(P('5', 'V', Decimal('1e-3'))[0], 0.005, 'a bare number is in the unit the grid shows')
        self.assertEqual(P('0.1', 'V', Decimal('1'))[0], 0.1)
        self.assertEqual(P('1.25 mV', 'V')[1], 3, 'significant figures as typed')
        self.assertEqual(P('0.0035 V', 'V')[1], 2)
        for bad in ('', 'abc', '0 mV', '-1 mV', '3 mA', '1e400 V', '3..5 mV', 'nan'):
            v, sig, err = P(bad, 'V')
            self.assertIsNone(v, bad)
            self.assertTrue(err, bad)

    def test_decimal_is_used(self):
        v, _, _ = M.parse_uncertainty('0.1 mV', 'V')
        self.assertEqual(v, float(Decimal('0.1') * Decimal('1e-3')))

    def test_typed_value_is_printed_as_entered_not_rounded_up(self):
        import uncertainty
        row = M.ReviewModel([oos_spec()], '5560A', asset='A-1').rows[0]
        self.assertEqual(row.status, M.NOT_IN_SCOPE)
        self.assertTrue(row.can_type())
        ok, msg = row.set_typed('0.0034 V')
        self.assertTrue(ok, msg)
        self.assertEqual(row.typed['display'], '3.4 mV')
        self.assertEqual(uncertainty.format_value(0.00341, 'V'), '3.5 mV', 'the computed path rounds UP')
        ok, _ = row.set_typed('3.41 mV')
        self.assertEqual(row.typed['display'], '3.41 mV', 'a typed value keeps the figures typed')
        self.assertEqual(row.status, M.MANUAL)
        self.assertEqual(row.reported_text, '3.41 mV')
        self.assertEqual(row.tar_text, '')
        import tartur
        self.assertEqual(row.tur_text, tartur.format_ratio(1.0 / 0.00341))
        self.assertTrue(row.needs_attention)

    def test_clearing_returns_to_the_engine_value(self):
        row = M.ReviewModel([oos_spec()], '5560A').rows[0]
        row.set_typed('5 mV')
        self.assertTrue(row.changed)
        ok, _ = row.set_typed('')
        self.assertTrue(ok)
        self.assertIsNone(row.typed)
        self.assertEqual(row.status, M.NOT_IN_SCOPE)
        self.assertEqual(row.reported_text, '760 mV')

    def test_in_scope_rows_do_not_allow_typing(self):
        app, _T = truevolt_app()
        specs, default = M.specs_for(app)
        model = M.ReviewModel(specs, default)
        for r in model.rows:
            if not r.spec.locked and r.cur.cmc is not None:
                ok, msg = r.set_typed('1 nV')
                self.assertFalse(ok)
                self.assertIsNone(r.typed)
                self.assertFalse(r.can_type())
        locked = [r for r in model.rows if r.spec.locked]
        self.assertTrue(all(not r.can_type() for r in locked))

    def test_record_carries_value_who_and_when(self):
        model = M.ReviewModel([oos_spec()], '5560A', asset='A-1')
        self.assertEqual(model.set_typed(0, '3.5 mV'), (True, ''))
        block = M.review_block([model], by='T. Tech', when='2026-10-24T10:00:00')
        ch = block['reviews'][0]['changes'][0]
        self.assertTrue(ch['manual'])
        self.assertEqual((ch['manual_value'], ch['manual_text'], ch['entered_by'], ch['entered_at']), (0.0035, '3.5 mV', 'T. Tech', '2026-10-24T10:00:00'))
        self.assertEqual(ch['status'], M.MANUAL)
        self.assertEqual(block['reviews'][0]['manual'], 1)
        json.dumps(block, allow_nan=False)
        model.reset()
        self.assertEqual(model.counts()['changed'], 0)

    @unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
    def test_typed_uncertainty_prints_and_regenerates(self):
        ctx = R.registry()
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        out = Path(tempfile.mkdtemp())
        s = oos_spec()
        model = M.ReviewModel([s], '5560A', asset='A-77')
        model.set_typed(0, '3.5 mV')
        rows = [report_pdf.cert_row('AC 1000 V range', 1000.0, 999.0, 1001.0, 'V', reading=1000.1, section='AC volts', uncertainty='760 mV')]
        rows[0]['Nominal'] = '1000 V @ 10 Hz'
        s2 = M.PointSpec(0, '9-9', 'AC volts', rows[0]['Description'], rows[0]['Nominal'], s.q, s.q, 999.0, 1001.0, 'V', '5560A', printed=dict(Uncertainty='760 mV'))
        model = M.ReviewModel([s2], '5560A', asset='A-77')
        self.assertEqual(model.set_typed(0, '3.5 mV'), (True, ''))
        details = dict(R.DETAILS, uncertainty_review=M.review_block([model], by='T. Tech'))
        pdf = out / 'm.pdf'
        report_pdf.write_calibration_pdf(str(pdf), rows, header=[('Instrument', 'X'), ('Instrument ID', 'A-77'), ('Serial', '1')], details=details)
        text = R.pdf_text(pdf)
        self.assertIn('3.5 mV', text)
        self.assertNotIn('760 mV', text)
        rid = labregistry.runs_for('A-77')[0]['id']
        snap = rs.load(rid)
        self.assertEqual(snap.status, rs.OK)
        self.assertEqual(snap.data['rows'][0]['Uncertainty'], '3.5 mV')
        self.assertEqual(snap.data['details']['uncertainty_review']['reviews'][0]['changes'][0]['entered_by'], 'T. Tech')
        again = out / 'm2.pdf'
        self.assertTrue(regenerate(rid, again).ok)
        self.assertEqual(R.differences(pdf, again, None), [])


class Wiring(unittest.TestCase):
    """The shared files stay out of every sidecar fingerprint list: nothing flips to 'Changed since verification'."""

    def test_new_and_edited_modules_are_in_no_sidecar_list(self):
        mine = {'report_review.py', 'report_review_model.py', 'report_dialog.py', 'report_pdf.py', 'report_snapshot.py', 'run_queue_engine.py'}
        for f in sorted((ROOT / 'Procedures').glob('*.procedure.json')):
            code = {c.split('#')[0] for c in json.loads(f.read_text(encoding='utf-8')).get('fingerprint', {}).get('code', [])}
            self.assertFalse(code & mine, f'{f.name} lists {code & mine}')
        import verified
        self.assertFalse(set(verified.USER_CODE) & mine)

    def test_engines_without_certificate_rows_and_points_are_not_covered(self):
        import report_review
        parent = object()

        class Pairs:                                             # fgen / MDO4000C / TDS2000C style: certificate_pairs only
            root = parent

            def certificate_pairs(self):
                return []
        keep = Pairs()
        self.assertIsNone(report_review.find_app(parent))
        self.assertIs(report_review.ask(parent, 'x'), report_review.UNAVAILABLE)
        del keep

    def test_app_is_found_by_its_root(self):
        import report_review
        parent = object()

        class Fake:
            def __init__(self):
                self.root = parent

            def certificate_rows_and_points(self):
                return [], []
        app = Fake()
        self.assertIs(report_review.find_app(parent), app)
        self.assertIs(report_review.find_app(object()), None)


if __name__ == '__main__':
    unittest.main()
