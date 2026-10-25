"""The review window's 'Why is there no uncertainty?' panel: the reasons, the one-click fixes, 'all points like this' rules and the quality flag."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import _tk_stub  # noqa: E402
_tk_stub.install()
import labregistry  # noqa: E402
import phase2_apps as P  # noqa: E402
import report_review_model as M  # noqa: E402
import uncertainty_fixes as F  # noqa: E402
import uncertainty_why as W  # noqa: E402

_APP = {}


def fgen():
    if 'fgen' not in _APP:
        _APP['fgen'] = P.fgen_app()
    return _APP['fgen']


def fake_spec(i, section='S', emu=None):
    spec = M.PointSpec(i, str(i + 1), section, f'point {i}', '1 V', dict(kind='ACV', nominal=1.0, unit='V', frequency=60e6), {}, 0.99, 1.01, 'V', None,
                       '', {'Uncertainty': ''}, expects=True, std_label='Fluke 5790B')
    spec.calc = lambda standard, _e=emu: M.make_evaluation('V', standard, '', _e, None, None, '', '', True)
    return spec


class TempRegistry(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        p = mock.patch.object(labregistry, 'DB', Path(self.dir.name) / 'lab_registry.sqlite3')
        p.start()
        self.addCleanup(p.stop)


class Diagnose(TempRegistry):
    def test_power_meter_flatness_says_what_is_missing_and_hints_the_wideband_method(self):
        app, _mod = fgen()
        specs, d = M.specs_for(app)
        model = M.ReviewModel(specs, d, asset='A-300', procedure='33220A')
        idx = next(i for i, r in enumerate(model.rows) if r.cur.status == M.NOT_IN_SCOPE and r.spec.q.get('kind') == 'FLAT')
        diag = W.diagnose(model, idx)
        kinds = [k for k, _t, _x in diag.reasons]
        self.assertEqual(kinds[:2], ['missing', 'missing'])
        self.assertTrue(any('WIDEBAND' in x for k, _t, x in diag.reasons if k == 'hint'), diag.reasons)
        self.assertEqual(diag.suggestions, [])                       # no spec, nothing used before: the calculator is the way

    def test_a_standard_spec_gives_a_one_click_value_rounded_up(self):
        model = M.ReviewModel([fake_spec(0, emu=0.00123)], None, procedure='P')
        diag = W.diagnose(model, 0)
        self.assertEqual(diag.suggestions[0].text, '1.3 mV')
        self.assertIn('specification', diag.suggestions[0].source)


class Fixes(TempRegistry):
    def model(self):
        return M.ReviewModel([fake_spec(0, 'S'), fake_spec(1, 'S'), fake_spec(2, 'Other')], None, procedure='P')

    def test_apply_types_the_value_with_its_source_and_remembers_it(self):
        m = self.model()
        ok, msg, n = W.apply(m, 0, '2 mV', 'Uncertainty Calculator', reason='bench check', who='mike')
        self.assertTrue(ok, msg)
        self.assertEqual(n, 1)
        self.assertEqual(m.rows[0].status, M.MANUAL)
        self.assertEqual(m.rows[0].typed['source'], 'Uncertainty Calculator')
        ch = m.changes(by='mike')[0]
        self.assertEqual((ch['manual_source'], ch['manual_reason']), ('Uncertainty Calculator', 'bench check'))
        self.assertIsNone(m.rows[1].typed)
        nxt = self.model()
        self.assertEqual(W.diagnose(nxt, 0).suggestions[0].text, '2 mV')    # same as last time

    def test_all_points_like_this_fills_the_section_now_and_in_later_runs(self):
        m = self.model()
        ok, _m, n = W.apply(m, 0, '2 mV', 'Uncertainty Calculator', like=True, who='mike')
        self.assertEqual(n, 2)                                        # rows 0 and 1 (same section and unit); row 2 is another section
        self.assertIsNone(m.rows[2].typed)
        later = self.model()
        self.assertEqual(W.apply_saved_rules(later), 2)
        self.assertTrue(later.rows[1].typed['source'].startswith('Saved rule'))
        self.assertIsNone(later.rows[2].typed)

    def test_a_point_in_scope_is_never_overridden(self):
        spec = fake_spec(0)
        spec.calc = lambda standard: M.make_evaluation('V', standard, '1 mV', 0.001, 0.0009, 0.001, '', '', True)
        m = M.ReviewModel([spec], None, procedure='P')
        ok, msg, _n = W.apply(m, 0, '2 mV', 'x')
        self.assertFalse(ok)
        self.assertEqual(W.diagnose(m, 0).suggestions, [])

    def test_flag_for_quality_is_listed(self):
        F.flag('P', 'A-1', 'S', '1 V point 0', 'no scope line', 'mike')
        self.assertEqual([f['description'] for f in F.flags()], ['1 V point 0'])


try:
    from PySide6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except Exception:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Panel(TempRegistry):
    @classmethod
    def setUpClass(cls):
        from qtui import app
        cls.app = app.create_app()

    def test_buttons_apply_and_the_calculator_result_is_used(self):
        from qtui.screens import uncertainty_why_dialog as D
        m = M.ReviewModel([fake_spec(0, emu=0.00123), fake_spec(1)], None, procedure='P')
        dlg = D.WhyDialog(None, m, 0)
        self.assertEqual(dlg.fix_buttons[0].text(), 'Use 1.3 mV')
        dlg.like.setChecked(True)
        self.assertTrue(dlg.use('1.3 mV', 'Fluke 5790B specification (k = 2)'))
        self.assertEqual(dlg.outcome, 'applied')
        self.assertEqual((m.rows[0].typed['display'], m.rows[1].typed['display']), ('1.3 mV', '1.3 mV'))
        m2 = M.ReviewModel([fake_spec(0), fake_spec(1, 'X')], None, procedure='Q')
        with mock.patch.object(D, '_calculator', lambda parent, prefill: '4.2 mV'):
            dlg2 = D.WhyDialog(None, m2, 1)
            self.assertTrue(dlg2.calculate())
        self.assertEqual(m2.rows[1].typed['source'], 'Uncertainty Calculator')

    def test_flag_button(self):
        from qtui.screens import uncertainty_why_dialog as D
        m = M.ReviewModel([fake_spec(0)], None, procedure='P')
        dlg = D.WhyDialog(None, m, 0, asset='A-9')
        dlg.flag_it()
        self.assertEqual(dlg.outcome, 'flagged')
        self.assertEqual(F.flags()[0]['asset'], 'A-9')


if __name__ == '__main__':
    unittest.main()
