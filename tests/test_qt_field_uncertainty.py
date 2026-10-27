"""Qt side of "Assign uncertainty": the panel (qtui/screens/field_uncertainty_panel.py), the call to action in the review window, the in-run hook
(field_uncertainty_view_qt.py) and the owner's list.  Driven with real events (QTest clicks, typing) offscreen on the Truevolt 34470A simulated bench plus two recorded
points the lab scope does not cover (tests/field_uncertainty_harness.py).  The core rules are in tests/test_field_uncertainty.py.

Skipped when PySide6 is missing.  Run:  QT_QPA_PLATFORM=offscreen python -m unittest tests.test_qt_field_uncertainty
"""
import contextlib
import csv
import os
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HOME = tempfile.mkdtemp()
os.environ['HOME'] = _HOME                                   # the throw-away user's saved settings
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    import _qt_test_support as support  # noqa: E402
    support.force_tk_stub()
    import field_uncertainty_harness as H  # noqa: E402
    import field_uncertainty as F  # noqa: E402
    import report_review_model as M  # noqa: E402
    from PySide6.QtCore import Qt  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
    from qtui import theme  # noqa: E402
    from qtui.screens import field_uncertainty_panel as P  # noqa: E402
    from qtui.screens import report_review as RR  # noqa: E402
    import field_uncertainty_view_qt as VIEW  # noqa: E402
    import field_uncertainty_view_tk as VIEW_TK  # noqa: E402

    get_app = support.get_app

WHO = 'A. Technician'
D = Decimal


def pump(n=3):
    for _ in range(n):
        QApplication.processEvents()


def click(w):
    QTest.mouseClick(w, Qt.MouseButton.LeftButton)
    pump()


def type_into(edit, text):
    edit.clear()
    QTest.keyClicks(edit, text)
    pump()


def pick_unit(d, text):
    i = d.unit_combo.findText(text)
    assert i >= 0, [d.unit_combo.itemText(k) for k in range(d.unit_combo.count())]
    d.unit_combo.setCurrentIndex(i)
    pump()


@unittest.skipUnless(HAVE_QT, 'PySide6 is needed')
class Base(unittest.TestCase):
    demo = False
    twin = False

    @classmethod
    def setUpClass(cls):
        cls.qapp = get_app()

    def setUp(self):
        F.clear_session()
        self.addCleanup(F.clear_session)
        self.app, self.mod = H.gap_app(demo=self.demo, twin=self.twin)
        self.addCleanup(H.drop_gap_points, self.mod)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.reg = stack.enter_context(H.registry())
        self.model = H.review_model(self.app, demo=self.demo)
        self.idx = sorted(self.model.field_missing)[0]
        self.root = QWidget()
        self.addCleanup(self.root.deleteLater)

    def dialog(self, idx=None, **kw):
        d = P.AssignDialog(self.root, self.model, self.idx if idx is None else idx, asset='A-100', demo=self.demo, **kw)
        self.addCleanup(d.deleteLater)
        d.show()
        pump()
        return d

    def stored(self):
        return F.all_assignments(True, self.demo)


class Panel(Base):
    twin = True

    def test_shows_the_point_why_and_ranked_suggestions(self):
        d = self.dialog()
        self.assertIn('2 MHz', d.point_title.text())
        self.assertEqual(d.facts['Kind'], 'ACV')
        self.assertIn('Lab CMC floor', d.facts)
        self.assertGreaterEqual(len(d.diag.reasons), 1)
        self.assertGreaterEqual(len(d.sug_buttons), 1)
        self.assertEqual(d.sug_buttons[0].text(), 'Use this')
        self.assertIn('V', d.suggested[0].line)
        self.assertFalse(d.btn_withdraw.isVisible())
        self.assertTrue(d.scope_point.isChecked())

    def test_one_tap_accepts_a_suggestion_once_a_name_is_there(self):
        d = self.dialog()
        d.who_edit.clear()
        click(d.sug_buttons[0])
        self.assertTrue(d.msg.isVisible())
        self.assertEqual(self.stored(), [], 'no name, nothing kept')
        type_into(d.who_edit, WHO)
        s = d.suggested[0]
        click(d.sug_buttons[0])
        rec = self.stored()
        self.assertEqual(len(rec), 1)
        self.assertEqual((rec[0]['source'], rec[0]['who'], D(rec[0]['value'])), (s.source, WHO, s.value))
        self.assertEqual(rec[0]['first_asset'], 'A-100')
        self.assertEqual(d.outcome, 'assigned')
        self.assertIsNotNone(self.model.rows[self.idx].assigned)
        self.assertEqual(d.who_edit.text(), WHO)
        self.assertEqual(self.dialog(self.idx).who_edit.text(), '', 'the name is never remembered: a new panel starts empty')
        self.assertFalse(hasattr(P, '_remembered_name'))

    def test_enter_my_own_value_with_unit_reason_and_name(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        pick_unit(d, 'mV')
        type_into(d.value_edit, '12.5')
        self.assertIn('12.5 mV', d.manual_msg.text())
        click(d.btn_manual)
        self.assertTrue(d.msg.isVisible() and 'reason' in d.msg.text_label.text().lower(), 'a reason is required for my own value')
        self.assertEqual(self.stored(), [])
        type_into(d.reason_edit, 'Verified against the scope on site')
        click(d.btn_manual)
        rec = self.stored()
        self.assertEqual(len(rec), 1)
        self.assertEqual((rec[0]['value'], rec[0]['display'], rec[0]['source']), ('0.0125', '12.5 mV', 'manual'))
        self.assertEqual(rec[0]['reason'], 'Verified against the scope on site')

    def test_my_value_validation_is_visible_and_blocks(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        type_into(d.reason_edit, 'Some real reason')
        for text in ('abc', '0', '-5', '1e99'):
            type_into(d.value_edit, text)
            self.assertFalse(d.btn_manual.isEnabled(), text)
            self.assertTrue(d.manual_msg.text(), text)
        pick_unit(d, 'mV')
        type_into(d.value_edit, '5000')                                   # 5 V on a 1 V point
        self.assertFalse(d.btn_manual.isEnabled())
        self.assertIn('larger than the nominal', d.manual_msg.text())

    def test_below_cmc_warns_visibly_and_needs_the_confirmation(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        type_into(d.reason_edit, 'Better than the lab line')
        pick_unit(d, 'mV')
        type_into(d.value_edit, '0.5')
        self.assertIn('Below the lab CMC', d.manual_msg.text())
        self.assertTrue(d.confirm_check.isVisibleTo(d))
        self.assertFalse(d.btn_manual.isEnabled())
        d.confirm_check.setChecked(True)
        pump()
        self.assertTrue(d.btn_manual.isEnabled())
        click(d.btn_manual)
        rec = self.stored()
        self.assertEqual((len(rec), rec[0]['below_cmc_confirmed']), (1, 1))

    def test_secrets_are_refused_in_the_panel_and_never_stored(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        type_into(d.reason_edit, 'the password is hunter2')
        click(d.sug_buttons[0])
        self.assertIn('password', d.msg.text_label.text().lower())
        self.assertNotIn('hunter2', d.msg.text_label.text())
        pick_unit(d, 'mV')
        type_into(d.value_edit, '12.5')
        click(d.btn_manual)
        self.assertEqual(self.stored(), [])

    def test_scope_choice_shows_the_count_and_is_safe(self):
        d = self.dialog()
        self.assertIn('2 other point(s) in this run print no uncertainty', d.scope_note.text())
        self.assertIn('same kind, level, frequency and range', d.scope_note.text())
        self.assertIn('spread only over the 1 point(s)', d.scope_note.text())      # the repeat at 2 MHz; the 5 MHz point has other conditions
        self.assertIn('1 with other conditions are left alone', d.scope_note.text())
        self.assertTrue(d.scope_kind.isEnabled())
        type_into(d.who_edit, WHO)
        type_into(d.reason_edit, 'Same fixture for both repeats')
        pick_unit(d, 'mV')
        type_into(d.value_edit, '12.5')
        seen = []
        d.confirm = lambda title, text: seen.append(text) or True
        d.scope_kind.setChecked(True)
        click(d.btn_manual)
        self.assertEqual(len(seen), 1)
        self.assertIn('1 other point(s) will be assigned', seen[0])
        self.assertIn('Hz filter', seen[0])
        self.assertNotIn('5 MHz', seen[0])
        rec = self.stored()
        self.assertEqual({r['scope'] for r in rec}, {'kind'})
        self.assertEqual(len(rec), 2)
        self.assertEqual(len({r['group_id'] for r in rec}), 1)
        self.assertEqual({r['display'] for r in rec}, {'12.5 mV'})

    def test_extrapolated_suggestions_are_never_spread(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        d.confirm = lambda title, text: self.fail('no confirmation expected')
        d.scope_kind.setChecked(True)
        click(d.sug_buttons[0])
        self.assertEqual(len(self.stored()), 1, 'a nearest-CMC suggestion describes one point only')

    def test_cancelling_the_group_confirmation_keeps_nothing(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        type_into(d.reason_edit, 'Same fixture for both repeats')
        pick_unit(d, 'mV')
        type_into(d.value_edit, '12.5')
        d.confirm = lambda title, text: False
        d.scope_kind.setChecked(True)
        click(d.btn_manual)
        self.assertEqual(self.stored(), [])

    def test_computed_point_is_locked_until_replace_with_a_reason(self):
        i = next(j for j, r in enumerate(self.model.rows) if j not in self.model.field_missing and str(r.spec.printed.get('Uncertainty') or '').strip() not in ('', 'N/A'))
        d = self.dialog(i)
        self.assertTrue(d.notice.isVisibleTo(d))
        self.assertIn('already prints a computed uncertainty', d.notice.text_label.text())
        self.assertTrue(d.replace_check.isVisibleTo(d))
        self.assertTrue(all(not b.isEnabled() for b in d.sug_buttons))
        type_into(d.who_edit, WHO)
        pick_unit(d, 'mV')
        type_into(d.value_edit, '0.7')
        self.assertFalse(d.btn_manual.isEnabled())
        d.replace_check.setChecked(True)
        d.confirm_check.setChecked(True)
        pump()
        type_into(d.reason_edit, 'Computed value is wrong for this fixture')
        d.confirm_check.setChecked(True)
        pump()
        self.assertTrue(d.btn_manual.isEnabled() or d.confirm_check.isVisibleTo(d))
        d.use_manual()
        rec = self.stored()
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]['replaces'], 1)

    def test_withdraw_from_the_panel(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        click(d.sug_buttons[0])
        d2 = self.dialog(self.idx)
        self.assertTrue(d2.btn_withdraw.isVisibleTo(d2))
        d2.ask_withdraw = lambda: (WHO, 'Entered on the wrong point')
        d2.withdraw_current()
        self.assertEqual(F.status_of(self.stored()[0]), 'withdrawn')
        self.assertIsNone(self.model.rows[self.idx].assigned)

    def test_name_is_not_persisted_anywhere_but_the_record(self):
        d = self.dialog()
        type_into(d.who_edit, 'Zed Uniquename')
        click(d.sug_buttons[0])
        self.assertEqual(self.stored()[0]['who'], 'Zed Uniquename')
        for root, _dirs, files in os.walk(_HOME):
            for f in files:
                self.assertNotIn(b'Uniquename', (Path(root) / f).read_bytes(), f)

    def test_withdraw_needs_a_reason_and_keeps_the_row(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        click(d.sug_buttons[0])
        d2 = self.dialog(self.idx)
        d2.ask_withdraw = lambda: (WHO, '')
        d2.withdraw_current()
        self.assertTrue(d2.msg.isVisibleTo(d2))
        self.assertEqual(F.status_of(self.stored()[0]), 'active')
        d2.ask_withdraw = lambda: (WHO, 'Wrong unit chosen')
        d2.withdraw_current()
        rec = self.stored()
        self.assertEqual((len(rec), F.status_of(rec[0]), rec[0]['withdrawn_reason']), (1, 'withdrawn', 'Wrong unit chosen'))

    def test_text_scales(self):
        for pct in (100, 150, 200):
            theme.set_text_scale(pct)
            self.addCleanup(theme.set_text_scale, 100)
            d = self.dialog()
            pump()
            pm = d.grab()
            self.assertFalse(pm.isNull(), pct)
            self.assertGreater(pm.width(), 600, pct)
            self.assertTrue(d.btn_manual.sizeHint().height() > 0)
            d.close()
        theme.set_text_scale(100)


class DemoPanel(Base):
    demo = True

    def test_demo_is_marked_and_nothing_is_persisted(self):
        d = self.dialog()
        self.assertIn('DEMO', d.windowTitle().upper())
        self.assertTrue(d.demo_banner.isVisibleTo(d))
        type_into(d.who_edit, WHO)
        click(d.sug_buttons[0])
        self.assertEqual(len(F.all_assignments(demo=True)), 1)
        self.assertFalse(self.reg.exists() and 'field_uncertainty' in __import__('test_field_uncertainty').tables(self.reg))
        self.assertEqual(F.all_assignments(demo=False), [])
        self.assertEqual(self.dialog().who_edit.text(), '')


class ReviewWindowCta(Base):
    def window(self, model=None):
        w = RR.ReviewWindow(self.root, model or self.model, 'Keysight 34470A performance verification', demo=self.demo)
        self.addCleanup(w.deleteLater)
        w.show()
        w.resize(1360, 860)
        pump()
        return w

    def test_cta_is_shown_only_for_points_without_uncertainty(self):
        w = self.window()
        self.assertTrue(w.cta_row.isVisibleTo(w))
        self.assertIn('No uncertainty for 2 points', w.cta.text_label.text())
        self.assertEqual(w.cta_btn.text(), 'Assign (2)')
        self.assertFalse(w.btn_assign.isEnabled())
        app, mod = H.gap_app()
        H.drop_gap_points(mod)
        app2, mod2 = __import__('test_reprint_review').truevolt_app()
        clean = H.review_model(app2)
        w2 = self.window(clean)
        self.assertFalse(w2.cta_row.isVisibleTo(w2))

    def test_needs_attention_counts_points_without_uncertainty(self):
        bare = M.ReviewModel(*M.specs_for(self.app), asset='A-100', procedure='p')
        self.assertEqual(bare.counts()['attention'], 0)
        self.assertEqual(self.model.counts()['attention'], 2)
        self.assertEqual(len(self.model.visible('Needs attention')), 2)
        self.window()
        s = F.suggestions(self.model, self.idx)[0]
        F.add(F.point_info(self.model, self.idx), s.value, source=s.source, reason='', who=WHO)
        model2 = H.review_model(self.app)
        self.assertEqual(model2.counts()['attention'], 1, 'an assigned point no longer needs attention')
        self.assertEqual(model2.counts()['all'], bare.counts()['all'])
        self.assertEqual({k: v for k, v in model2.counts().items() if k not in ('attention', M.ASSIGNED, M.NO_UNC)}.get('changed'), 0)

    def test_assign_from_the_window_updates_the_row(self):
        w = self.window()
        seen = {}

        def fake_run(dlg):
            seen['idx'] = dlg.idx
            type_into(dlg.who_edit, WHO)
            click(dlg.sug_buttons[0])
            return dlg.outcome
        with mock.patch.object(P.AssignDialog, 'run', fake_run):
            out = w.assign(first=True)
        self.assertEqual(out, 'assigned')
        row = self.model.rows[seen['idx']]
        self.assertIsNotNone(row.assigned)
        self.assertIn('assigned in the field', row.reported_text)
        self.assertEqual(row.status, M.ASSIGNED)
        self.assertEqual(w.cta_btn.text(), 'Assign')
        self.assertIn('No uncertainty for this point', w.cta.text_label.text())
        self.assertEqual(self.model.counts().get(M.ASSIGNED), 1)

    def test_assign_button_follows_the_selection(self):
        w = self.window()
        gap = self.model.rows[self.idx]
        w.table.select_rows([gap])
        pump()
        self.assertTrue(w.btn_assign.isEnabled())


class InRunHook(Base):
    class Shell:
        def __init__(self):
            self.root = QWidget()
            self.actions = []

        def add_action(self, text, cmd, short=None, **k):
            from PySide6.QtWidgets import QPushButton
            b = QPushButton(text, self.root)
            self.actions.append((text, cmd, b))
            return b

    def test_button_appears_only_when_a_recorded_point_has_no_uncertainty(self):
        shell = self.Shell()
        self.addCleanup(shell.root.deleteLater)
        hook = VIEW.attach(self.app, shell, poll_ms=60000)
        self.addCleanup(hook.timer.stop)
        self.assertEqual(hook.refresh(force=True), 2)
        self.assertEqual([a[0] for a in shell.actions], [VIEW.LABEL])
        self.assertFalse(shell.actions[0][2].isHidden())
        self.assertIn('2 recorded point(s)', shell.actions[0][2].toolTip())

    def test_nothing_is_added_to_a_clean_run(self):
        app, mod = __import__('test_reprint_review').truevolt_app()
        shell = self.Shell()
        self.addCleanup(shell.root.deleteLater)
        hook = VIEW.attach(app, shell, poll_ms=60000)
        self.addCleanup(hook.timer.stop)
        self.assertEqual(hook.refresh(force=True), 0)
        self.assertEqual(shell.actions, [])

    def test_opening_assigns_and_the_count_drops(self):
        shell = self.Shell()
        self.addCleanup(shell.root.deleteLater)
        hook = VIEW.attach(self.app, shell, poll_ms=60000)
        self.addCleanup(hook.timer.stop)
        hook.refresh(force=True)

        def fake_run(dlg):
            type_into(dlg.who_edit, WHO)
            click(dlg.sug_buttons[0])
            return dlg.outcome
        with mock.patch.object(P.AssignDialog, 'run', fake_run):
            out = hook.open()
        self.assertEqual(out, 'assigned')
        self.assertEqual(hook.count, 1)
        self.assertEqual(len(F.all_assignments()), 1)

    def test_a_broken_engine_never_raises_into_the_run(self):
        shell = self.Shell()
        self.addCleanup(shell.root.deleteLater)
        hook = VIEW.attach(object(), shell, poll_ms=60000)
        self.addCleanup(hook.timer.stop)
        self.assertEqual(hook.refresh(force=True), 0)

    def test_tk_has_no_window(self):
        self.assertIsNone(VIEW_TK.attach(self.app, object()))


class OwnerList(Base):
    def make(self):
        d = self.dialog()
        type_into(d.who_edit, WHO)
        click(d.sug_buttons[0])
        return d

    def list_dialog(self):
        dlg = P.FieldAssignmentsDialog(self.root, demo=self.demo)
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        pump()
        return dlg

    def test_empty_then_listed(self):
        dlg = self.list_dialog()
        self.assertIn('0 assignment(s)', dlg.count_label.text())
        self.make()
        dlg.reload()
        self.assertIn('1 assignment(s), 1 in use', dlg.count_label.text())
        row = dlg.rows[0]
        texts = [col.text(row) for col in dlg.table.source_model.columns]
        joined = ' | '.join(texts)
        for needle in ('active', 'truevolt_verification:34470A', '2 MHz', WHO, 'suggestion: '):
            self.assertIn(needle, joined)

    def test_export_csv_and_withdraw(self):
        self.make()
        dlg = self.list_dialog()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        out = tmp / 'field.csv'
        dlg.ask_save_path = lambda: str(out)
        dlg.export()
        rows = list(csv.reader(out.read_text(encoding='utf-8-sig').splitlines()))
        self.assertEqual(tuple(rows[0]), F.CSV_COLUMNS)
        self.assertEqual(len(rows), 2)
        self.assertIn('Exported 1', dlg.status_line.text())
        dlg.table.select_rows([dlg.rows[0]])
        pump()
        dlg.ask_withdraw = lambda: (WHO, 'Not needed any more')
        dlg.withdraw()
        self.assertEqual(F.status_of(F.all_assignments()[0]), 'withdrawn')
        self.assertIn('Withdrawn', dlg.status_line.text())


if __name__ == '__main__':
    unittest.main()
