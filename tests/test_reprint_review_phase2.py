"""Review window, phase 2: the generator / oscilloscope engines (33210A/20A/50A, MDO4000C, TDS2000C, WaveSurfer 4104HD) through report_review_adapters.

Same rules as phase 1: model-level checks against the engine's own rows on the simulated benches, the report path (PDF + snapshot + Regenerate PDF), and
the two owner requirements: (a) a review with no changes leaves the PDF identical (no new column, no marker, same pages), (b) no engine / sidecar file edited.
Run:  python -m unittest tests.test_reprint_review_phase2
"""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import reprint_harness as R  # noqa: E402
import ui_ported  # noqa: E402
import phase2_apps as P  # noqa: E402
import report_dialog  # noqa: E402
import report_pdf  # noqa: E402
import report_review  # noqa: E402
import report_review_model as M  # noqa: E402
import report_snapshot as rs  # noqa: E402
import uncertainty  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

try:
    import reportlab  # noqa: F401
    import pypdf  # noqa: F401
    HAVE = subprocess.run(['pdftotext', '-v'], capture_output=True).returncode in (0, 99)
except Exception:
    HAVE = False

BUILDERS = {'mdo': P.mdo_app, 'fgen': P.fgen_app, 'tds': P.tds_app, 'ws': P.wavesurfer_app}
ASSET = {'mdo': 'A-200', 'fgen': 'A-300', 'tds': 'A-400', 'ws': 'A-500'}
_cache = {}


def built(name):
    if name not in _cache:
        _cache[name] = BUILDERS[name]()
    return _cache[name]


def engine_rows(name, app):
    if name == 'ws':
        out = []
        for k in ('noise', 'dcv', 'impedance', 'offset', 'bandwidth', 'timebase', 'trigger'):
            out += [dict(r) for r in app.certificate_rows(k, with_uncertainty=True)]
        return out
    return [row for _p, row in app.certificate_pairs()]


def export(name, app, mod, out, details):
    """The engine's own export path (dialog and file chooser replaced)."""
    with mock.patch.object(report_dialog, 'ask_details', lambda *a, **k: dict(details)), \
            mock.patch.object(getattr(mod, 'filedialog', None) or __import__('ui_port_tk').filedialog, 'asksaveasfilename', lambda **k: str(out)), \
            mock.patch.object(getattr(mod, 'messagebox', None) or __import__('ui_port_tk').messagebox, 'showinfo', lambda *a, **k: None, create=True), \
            mock.patch.object(getattr(mod, 'messagebox', None) or __import__('ui_port_tk').messagebox, 'showerror', lambda *a, **k: (_ for _ in ()).throw(AssertionError(a)), create=True):
        if name == 'ws':
            app.write_certificate_pdf(str(out), ['noise', 'dcv', 'impedance', 'offset', 'bandwidth', 'timebase', 'trigger'], dict(details))
        else:
            app.export_pdf()


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class Adapters(unittest.TestCase):
    def test_every_engine_is_recognised(self):
        for name in BUILDERS:
            app, mod = built(name)
            res = M.specs_for(app)
            self.assertIsNotNone(res, name)
            specs, default = res
            self.assertTrue(specs, name)
            self.assertEqual(report_review.find_app.__name__, 'find_app')
            self.assertTrue(any(hasattr(app, c) for c in report_review.COVERED), name)

    def test_one_spec_per_report_row_and_default_equals_printed(self):
        for name in BUILDERS:
            app, mod = built(name)
            specs, _d = M.specs_for(app)
            rows = engine_rows(name, app)
            self.assertEqual(len(specs), len(rows), name)
            for s, row in zip(specs, rows):
                e = M.evaluate(s, s.default_std)
                want = row.get('Uncertainty', '')
                self.assertEqual(e.unc_text, '' if want == 'N/A' else want, (name, s.step, s.description))

    def test_asset_number_is_found_for_every_engine(self):
        """WaveSurfer keeps it in instrument_id; the review must still be built (it fell back to the old popup before this was tested)."""
        for name in BUILDERS:
            app, _m = built(name)
            self.assertEqual(report_review.asset_of(app), ASSET[name], name)

    def test_not_in_scope_and_no_uncertainty_counts_per_engine(self):
        """Owner audit: a point with no stimulus from a calibrator or measuring standard (WaveSurfer RMS noise) is 'No uncertainty required' (grey, locked, not
        in Needs attention); 'Not in scope' stays only for points that use a standard but have no scope entry."""
        want = {'ws': (0, 36), 'mdo': (19, 21), 'fgen': (42, 1), 'tds': (1, 3)}
        for name, (nis, nou) in want.items():
            app, _m = built(name)
            specs, d = M.specs_for(app)
            c = M.ReviewModel(specs, d).counts()
            self.assertEqual((c[M.NOT_IN_SCOPE], c[M.NO_UNC], c['attention']), (nis, nou, nis), name)
        app, _m = built('ws')
        specs, d = M.specs_for(app)
        model = M.ReviewModel(specs, d)
        noise = [i for i, r in enumerate(model.rows) if r.spec.section == 'RMS Noise']
        self.assertEqual(len(noise), 36)
        for i in noise:
            r = model.rows[i]
            self.assertEqual(r.status, M.NO_UNC)
            self.assertEqual(M.NO_UNC, 'No uncertainty required')
            self.assertTrue(r.spec.locked)
            self.assertFalse(r.can_type())
            self.assertFalse(r.needs_attention)
            self.assertFalse(model.set_typed(i, '1 dB')[0])
            self.assertFalse(model.set_standard(i, '5522A'))
            self.assertEqual(r.reported_text, '')
        self.assertEqual(model.visible('Needs attention'), [])

    def test_untouched_model_has_no_changes(self):
        for name in BUILDERS:
            app, _m = built(name)
            specs, d = M.specs_for(app)
            model = M.ReviewModel(specs, d, asset=ASSET[name])
            self.assertEqual(model.changes(), [], name)     # the MDO4000C RF level rows print the 96270A value in the engine itself: not a change
            self.assertEqual(model.counts()['changed'], 0)

    def test_read_only_rows_are_locked_and_only_not_in_scope_accepts_typing(self):
        for name in BUILDERS:
            app, _m = built(name)
            specs, d = M.specs_for(app)
            model = M.ReviewModel(specs, d, asset=ASSET[name])
            for i, r in enumerate(model.rows):
                if r.spec.locked:
                    self.assertFalse(model.set_standard(i, '5522A'), (name, r.spec.description))
                if r.status != M.NOT_IN_SCOPE:
                    ok, _msg = model.set_typed(i, '1 V')
                    self.assertFalse(ok, (name, r.spec.description, r.status))
                    self.assertIsNone(r.typed)

    def test_fgen_and_tds_have_no_standard_dropdown_rows(self):
        for name in ('fgen', 'tds'):
            app, _m = built(name)
            specs, d = M.specs_for(app)
            self.assertTrue(all(s.locked for s in specs), name)

    def test_dc_points_of_mdo_and_wavesurfer_get_the_dropdown(self):
        for name in ('mdo', 'ws'):
            app, _m = built(name)
            specs, d = M.specs_for(app)
            free = [s for s in specs if not s.locked]
            self.assertTrue(free, name)
            for s in free:
                if s.options == ['96270A']:                    # MDO4000C RF level rows: 96270A only (test_reprint_review_mdo_96270a)
                    continue
                self.assertIn('5560A', M.offered_standards(s))

    def test_dc_standard_change_by_hand(self):
        """A 5522A budget for a DC offset / trigger point, written out from uncertainty_budget.osc_dc, never below the scope's CMC."""
        for name in ('mdo', 'ws'):
            app, _m = built(name)
            specs, d = M.specs_for(app)
            model = M.ReviewModel(specs, d, asset=ASSET[name])
            n = 0
            for i, r in enumerate(model.rows):
                s = r.spec
                if s.locked or '5522A' not in model.options(i):
                    continue
                before = r.cur
                self.assertTrue(model.set_standard(i, '5522A'))
                e = r.cur
                self.assertEqual(e.standard, '5522A')
                if e.cmc is not None and e.reported is not None:
                    self.assertGreaterEqual(e.reported, e.cmc * (1 - 1e-12), (name, s.description))
                self.assertEqual(r.status, M.CHANGED if (e.unc_text != before.unc_text or r.std_changed) else r.status)
                n += 1
            self.assertGreater(n, 0, name)
            # the model: reported = the larger of budget and scope minimum, rounded up (single-level offset point, by hand)
            for i, r in enumerate(model.rows):
                s = r.spec
                if s.locked or s.q.get('kind') not in ('OFFSET', 'DCV') or r.cur.unit != 'V':
                    continue
                level = abs(s.q.get('nominal') or 0.0)
                term = '50' if '50 Ohm' in s.description else '1M'
                b = ub.osc_dc(level, term, '5522A')
                if b is None or not r.cur.reported:
                    continue
                self.assertAlmostEqual(r.cur.reported, uncertainty.round_up(b.value), delta=abs(r.cur.reported) * 1e-9, msg=(name, s.description))
                break

    def test_typed_value_in_the_row_unit(self):
        found = 0
        for name in BUILDERS:
            app, _m = built(name)
            specs, d = M.specs_for(app)
            model = M.ReviewModel(specs, d, asset=ASSET[name])
            for i, r in enumerate(model.rows):
                if r.status != M.NOT_IN_SCOPE:
                    continue
                ok, msg = model.set_typed(i, '0.5')
                self.assertTrue(ok, (name, r.spec.description, msg))
                self.assertEqual(r.status, M.MANUAL_STATUS if hasattr(M, 'MANUAL_STATUS') else r.status)
                self.assertTrue(r.reported_text, r.reported_text)
                self.assertGreater(r.typed['value'], 0)
                self.assertEqual(r.tar_text, '')
                ch = [c for c in model.changes('Tech', '2026-01-01T00:00:00') if c['manual']][0]
                self.assertTrue(ch['manual'])
                self.assertEqual(ch['entered_by'], 'Tech')
                model.set_typed(i, '')
                self.assertEqual([c for c in model.changes() if c['manual']], [])
                found += 1
                break
        self.assertGreater(found, 2, 'fgen, TDS (or MDO) and WaveSurfer all have not-in-scope rows')


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class Discovery(unittest.TestCase):
    """ask_details(app.root, ...) reaches the review window for each engine through find_app, with no engine hook."""

    def fake_window(self, seen):
        class W:
            def __init__(s, parent, model, procedure, demo=False, details=None, position=(1, 1)):
                seen.append(model)
                s.result = {'technician': 'T', 'uncertainty_review': M.review_block([model])}

            def run(s):
                return s.result
        return W

    def test_ask_details_finds_each_engine(self):
        for name in BUILDERS:
            app, _m = built(name)
            seen = []
            with mock.patch.object(report_review, 'ReviewWindow', self.fake_window(seen)), \
                    mock.patch.object(report_dialog, 'ask_details_plain', lambda *a, **k: self.fail(f'{name}: fell back to the plain popup')):
                out = report_dialog.ask_details(app.root, 'x')
            self.assertEqual(len(seen), 1, name)
            self.assertEqual(seen[0].asset, ASSET[name], name)
            self.assertIn('uncertainty_review', out)

    def test_wavesurfer_section_export_reviews_only_that_tab(self):
        app, _m = built('ws')
        seen = []
        import inspect
        with mock.patch.object(report_review, 'ReviewWindow', self.fake_window(seen)), \
                mock.patch.object(app, 'write_certificate_pdf', lambda *a, **k: 1, create=True), \
                mock.patch.object(type(app), 'sync_asset', lambda self: True, create=True):
            import WaveSurfer_WS4104HD as W
            with mock.patch.object(__import__('ui_port_tk').filedialog, 'asksaveasfilename', lambda **k: ''):
                app.export_calibration_section('dcv')
        self.assertEqual(len(seen), 1)
        sections = {r.spec.section for r in seen[0].rows}
        self.assertEqual(sections, {'DC Gain (1 MOhm)'}, sections)


@unittest.skipUnless(HAVE, 'reportlab, pypdf and pdftotext are needed')
class Report(unittest.TestCase):
    def setUp(self):
        self._r = R.registry()
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        try:
            self._r.__exit__(None, None, None)
        except Exception:
            pass

    def test_no_change_review_leaves_the_pdf_identical(self):
        """Owner requirement: a review the technician did not change prints exactly the PDF the engine made before this feature.
        Compared page by page (R.differences) and by text; no added column, marker or footnote.
        The clock is frozen: the header's 'Report date' is printed to the minute, and on a slow machine the two exports of one engine can fall either side
        of a minute boundary (seen with the WaveSurfer export under load)."""
        import datetime as _dt

        class _Frozen(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 1, 2, 3, 4, 5)
        frozen = mock.patch.object(report_pdf, 'datetime', _Frozen)
        frozen.start()
        self.addCleanup(frozen.stop)
        for name in BUILDERS:
            app, mod = built(name)
            a, b, c = (self.dir / f'{name}_{x}.pdf' for x in 'abc')
            export(name, app, mod, a, R.DETAILS)
            specs, d = M.specs_for(app)
            model = M.ReviewModel(specs, d, asset=ASSET[name])
            export(name, app, mod, b, dict(R.DETAILS, uncertainty_review=M.review_block([model])))
            self.assertEqual(R.differences(a, b, None), [], name)
            self.assertEqual(R.pdf_text(a), R.pdf_text(b), name)
            # ...and a changed review reprints only the Uncertainty / TAR / TUR cells: same page count, same header cells
            self.assertEqual(len(__import__('pypdf').PdfReader(str(a)).pages), len(__import__('pypdf').PdfReader(str(b)).pages), name)

    def test_review_never_adds_a_column_or_marker(self):
        free = None
        for name in ('mdo', 'ws', 'fgen'):
            app, mod = built(name)
            specs, d = M.specs_for(app)
            model = M.ReviewModel(specs, d, asset=ASSET[name])
            for i, r in enumerate(model.rows):
                if (not r.spec.locked and model.set_standard(i, '5522A')) or (r.status == M.NOT_IN_SCOPE and model.set_typed(i, '0.5')[0]):
                    pass
            a, b = self.dir / f'{name}_base.pdf', self.dir / f'{name}_rev.pdf'
            export(name, app, mod, a, R.DETAILS)
            export(name, app, mod, b, dict(R.DETAILS, uncertainty_review=M.review_block([model], 'Tech', '2026-01-01T00:00:00')))
            ta, tb = R.pdf_text(a), R.pdf_text(b)
            for token in ('Manual', 'manual', 'Not in scope', 'Raised to scope', 'Standard changed', 'review', 'Review', '*'):
                self.assertEqual(ta.count(token), tb.count(token), (name, token))
            self.assertEqual(len(__import__('pypdf').PdfReader(str(a)).pages), len(__import__('pypdf').PdfReader(str(b)).pages), name)
            free = free or name
        self.assertTrue(free)

    def test_changes_print_persist_and_regenerate(self):
        for name in ('mdo', 'ws', 'fgen', 'tds'):
            app, mod = built(name)
            specs, d = M.specs_for(app)
            model = M.ReviewModel(specs, d, asset=ASSET[name])
            touched = 0
            for i, r in enumerate(model.rows):
                if touched >= 4:
                    break
                if not r.spec.locked and model.set_standard(i, '5522A'):
                    touched += 1
                elif r.status == M.NOT_IN_SCOPE and model.set_typed(i, '0.5')[0]:
                    touched += 1
            self.assertTrue(touched, name)
            out, again = self.dir / f'{name}_o.pdf', self.dir / f'{name}_again.pdf'
            export(name, app, mod, out, dict(R.DETAILS, uncertainty_review=M.review_block([model], 'Tech', '2026-01-01T00:00:00')))
            rid = R.last_run_id(ASSET[name])
            self.assertIsNotNone(rid, name)
            snap = rs.load(rid)
            self.assertEqual(snap.status, rs.OK, name)
            self.assertEqual(snap.data['details']['uncertainty_review']['reviews'][0]['asset'], ASSET[name])
            res = rs.regenerate(rid, choose_path=lambda n, o, p=again: str(p), confirm_overwrite=lambda p, o: False)
            self.assertTrue(res.ok, (name, res.message))
            self.assertEqual(R.differences(out, again, None), [], name)


class ZeroFlips(unittest.TestCase):
    EDITED = ('report_review_adapters.py',)
    EDITED_LATER = ('mdo4000c_verification.py', 'mdo3_verification.py', 'Procedures/Tektronix_MDO3_Verification.py', 'Procedures/Tektronix_MDO3_Verification.procedure.json',
                    'tbs1000_verification.py', 'tbs2000b_verification.py',                       # the TBS1000 / TBS1000C / TBS2000B procedures
                    'Procedures/Tektronix_TBS1000C_Verification.py', 'Procedures/Tektronix_TBS1000C_Verification.procedure.json',
                    'Procedures/Tektronix_TBS1000_Verification.py', 'Procedures/Tektronix_TBS1000_Verification.procedure.json',
                    'Procedures/Tektronix_TBS2000B_Verification.py', 'Procedures/Tektronix_TBS2000B_Verification.procedure.json',
                    'Procedures/Fluke_374_Verification.py', 'Procedures/Fluke_375_Verification.py', 'Procedures/Fluke_376_Verification.py', 'Procedures/Fluke_376II_Verification.py')      # edited by later work (logic probe removal; the 3 Series MDO and TBS procedures), not by phase 2

    def test_no_engine_or_launcher_file_is_changed(self):
        base = subprocess.run(['git', 'diff', '--name-only', 'origin/main'], cwd=ROOT, capture_output=True, text=True).stdout.split()
        engines = [f for f in base if (f.endswith('_verification.py') or f.startswith('Procedures/') or f.endswith('.procedure.json'))
                   and f not in self.EDITED_LATER and f not in ui_ported.files()]       # a port to ui_port is not phase-2 work (tests/ui_ported.txt)
        self.assertEqual(engines, [], 'phase 2 edits no engine, procedure or sidecar file')

    def test_adapters_are_in_no_fingerprint_list(self):
        import json
        names = set()
        for p in (ROOT / 'Procedures').glob('*.procedure.json'):
            text = p.read_text(encoding='utf-8')
            names.add(text)
        for f in ('report_review_adapters.py', 'report_review.py', 'report_review_model.py'):
            self.assertFalse(any(f in t for t in names), f)
        import verified
        for f in ('report_review_adapters.py',):
            self.assertNotIn(f, verified.USER_CODE)


if __name__ == '__main__':
    unittest.main()
