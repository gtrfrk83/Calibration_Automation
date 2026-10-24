"""Qt review window (qtui/screens/report_review.py), the report details popup (qtui/screens/report_details.py) and the Tk / Qt switch of report_dialog.

Drives the same scenarios as the Tk tests (tests/test_reprint_review*.py, tests/real_tk_review*.py) through the Qt window with real events (QTest clicks,
key presses, the cell editors) on the engines' simulated benches: a standard change recalculates the budget by hand, the reported value never drops below
the scope minimum, a not-in-scope point takes a typed uncertainty, 'No uncertainty required' rows are locked, Reset, filters, bulk change, Generate /
Cancel, the details record, and 'Regenerate PDF' reprints it identically.  The model results are compared with the toolkit-free model (report_review_model.py)
that the Tk window uses, so a Qt-driven result equals the Tk-driven result by construction and by test.

Skipped when PySide6 (or reportlab / pypdf / pdftotext) is missing.  File name sorts after test_beta (reprint_harness installs the tkinter stub).
Run (venv with PySide6):  python -m unittest tests.test_qt_report_review
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HOME = tempfile.mkdtemp()
os.environ['HOME'] = _HOME                                   # report_details.json / report_tartur.json of the throw-away user
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
    import reprint_harness as R  # noqa: E402  (installs the tkinter stub)
    import test_reprint_review as T  # noqa: E402  (truevolt_app, export, regenerate, hand_budget, oos_spec: the Tk tests' own helpers)
    import report_dialog  # noqa: E402
    import report_pdf  # noqa: E402
    import report_review_flow as F  # noqa: E402
    import report_review_model as M  # noqa: E402
    import report_snapshot as rs  # noqa: E402
    import ui_theme_core as core  # noqa: E402
    from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
    from PySide6.QtTest import QTest  # noqa: E402
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMainWindow, QWidget  # noqa: E402
    from qtui.screens import report_details as RD  # noqa: E402
    from qtui.screens import report_review as RR  # noqa: E402

    get_app = support.get_app

READY = HAVE_QT and T.HAVE
WHY = 'PySide6, reportlab, pypdf and pdftotext are needed'


def pump(n=3):
    for _ in range(n):
        QApplication.processEvents()


def cell(w, idx, key):
    """The proxy index of the cell (row with spec.idx, column key)."""
    t = w.table
    col = t.column_index(key)
    for i in range(t.proxy.rowCount()):
        ix = t.proxy.index(i, col)
        if t.row_of(ix).spec.idx == idx:
            return ix
    raise KeyError(idx)


def click(w, idx, key):
    ix = cell(w, idx, key)
    w.table.scrollTo(ix)
    pump(1)
    QTest.mouseClick(w.table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, w.table.visualRect(ix).center())
    pump()
    return ix


def pick_in_combo(w, ix, text):
    """The drop-down editor of the cell is open (a click opened it): choose `text` as the operator would."""
    ed = w.table.indexWidget(ix)
    assert isinstance(ed, QComboBox), ed
    i = ed.findText(text)
    assert i >= 0, (text, [ed.itemText(k) for k in range(ed.count())])
    ed.setCurrentIndex(i)
    ed.activated.emit(i)
    pump()


def tk_row_values(r):
    """The Tk window's row_values (report_review.ReviewWindow.row_values), minus the drop-down arrow: the reference the Qt cells are compared with."""
    s, e = r.spec, r.cur
    if s.locked and s.q.get('kind') == 'FREQ':
        std = M.LOCKED_FREQUENCY
    elif s.locked:
        std = s.std_label or '—'
    else:
        std = M.label(r.standard)
    unit = e.unit
    budget = M.fmt(e.budget, unit) or '—'
    scope = M.fmt(e.cmc, unit) or ('not in scope' if e.status != M.NO_UNC else '—')
    rep = r.reported_text or '—'
    if r.can_type() and r.typed is None:
        rep += '  [type]'
    tur = r.tur_text or '—'
    return (s.step, f'{s.nominal_text}  ·  {s.description}', M.tolerance_text(s) or '—', std, budget, scope, rep, tur, r.cur.status if r.status == M.CHANGED else r.status)    # Qt: a changed standard turns the row text blue and the badge keeps saying what the uncertainty did


def cell_texts(w, idx):
    """The visible text of every cell of the row, as the table shows it (without the check box column)."""
    t = w.table
    row = next(r for r in w.model.rows if r.spec.idx == idx)
    return tuple(t.source_model.columns[c].text(row) for c in range(1, len(t.source_model.columns)))


@unittest.skipUnless(READY, WHY)
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = get_app()
        cls.app, cls.T = T.truevolt_app()
        cls.specs, cls.default = M.specs_for(cls.app)

    def setUp(self):
        self.root = QWidget()
        self.addCleanup(self.root.deleteLater)
        self.model = M.ReviewModel(self.specs, self.default, asset='A-100', procedure='Keysight 34470A performance verification')
        self.windows = []

    def window(self, model=None, **kw):
        w = RR.ReviewWindow(self.root, model or self.model, 'Keysight 34470A performance verification', **kw)
        self.windows.append(w)
        self.addCleanup(w.deleteLater)
        w.show()
        w.resize(1360, 860)
        pump()
        return w

    def free_rows(self, model=None, n=None, need_other=True):
        m = model or self.model
        out = [r.spec.idx for r in m.rows if not r.spec.locked and len(m.options(r.spec.idx)) > 1 and r.cur.status != M.NOT_IN_SCOPE]
        return out[:n] if n else out

    def other(self, idx, model=None):
        m = model or self.model
        return [k for k in m.options(idx) if k != m.rows[idx].spec.default_std][0]


# =====================================================================================================================  the window
class Window(Base):
    def test_builds_and_every_cell_equals_the_tk_row_values(self):
        w = self.window()
        self.assertEqual(w.windowTitle(), 'Review uncertainties before generating the PDF')
        self.assertEqual(w.table.row_count(), (len(self.model.rows),) * 2)
        for r in self.model.rows:
            self.assertEqual(cell_texts(w, r.spec.idx), tk_row_values(r), (r.spec.step, r.spec.description))
            self.assertEqual(w.row_values(r), tk_row_values(r))
        c = self.model.counts()
        self.assertEqual(w.header.sub_label.text(), f'Keysight 34470A performance verification · Asset A-100 · {c["all"] - c[M.NO_UNC]} of {c["all"]} points carry an uncertainty')
        for key, pill in w.pills.items():
            self.assertEqual(pill.text(), f'{c.get(key, 0)} {RR.SHORT[key]}')
        self.assertEqual(w.btn_ok.text(), 'Generate PDF')
        self.assertFalse(w.btn_reset.isEnabled(), 'nothing changed yet')
        self.assertEqual(w.default_box.currentText(), 'Fluke 5560A')
        offered = sorted({k for r in self.model.rows if not r.spec.locked for k in self.model.options(r.spec.idx)}, key=M.SOURCE_STANDARDS.index)
        self.assertEqual([w.default_box.itemText(i) for i in range(w.default_box.count())], [M.label(k) for k in offered])
        self.assertEqual(offered[:2], ['5560A', '5522A'])
        self.assertEqual(w.filter, 'All')
        self.assertIn('Reported = larger of Budget and Scope minimum', w.note.text())
        self.assertFalse(w.bulk_box.isEnabled())

    def test_status_badges_and_row_kinds(self):
        w = self.window()
        badges = {r.status: w.table.source_model.data(w.table.proxy.mapToSource(cell(w, r.spec.idx, 'status')), 0x0100 + 3) for r in self.model.rows}
        # BADGE_ROLE = UserRole + 3
        self.assertEqual(badges.get(M.AS_BUDGETED), 'good')
        self.assertEqual(badges.get(M.RAISED), 'warn')
        self.assertEqual(badges.get(M.NO_UNC), 'neutral')

    def test_standard_change_through_the_cell_editor_recalculates_by_hand(self):
        s = next(x for x in self.specs if not x.locked and x.q['kind'] == 'DCV' and x.q['nominal'] > 0 and not x.q.get('frequency'))
        w = self.window()
        row = self.model.rows[s.idx]
        before = self.model.table()
        ix = click(w, s.idx, 'std')
        pick_in_combo(w, ix, 'Fluke 5522A')
        self.assertEqual(row.standard, '5522A')
        emu, cmc, reported = T.hand_budget('DCV', s.q['nominal'], s.q['unit'], '5522A')
        self.assertAlmostEqual(row.cur.budget, emu, delta=emu * 1e-9)
        self.assertAlmostEqual(row.cur.cmc, cmc, delta=cmc * 1e-9)
        self.assertAlmostEqual(row.cur.reported, reported, delta=reported * 1e-9)
        self.assertGreaterEqual(row.cur.reported, row.cur.cmc)
        self.assertEqual(row.status, M.CHANGED)
        self.assertEqual(w.pills['Standard changed'].text(), '1 changed')
        self.assertTrue(w.btn_reset.isEnabled())
        self.assertEqual(cell_texts(w, s.idx), tk_row_values(row), 'the grid shows the recalculated row')
        self.assertEqual(cell_texts(w, s.idx)[8], row.cur.status)        # the badge keeps the uncertainty's own status; the row text is blue
        self.assertNotEqual(self.model.table(), before)
        # the same change made directly on a model gives the identical record
        twin = M.ReviewModel(self.specs, self.default, asset='A-100', procedure='Keysight 34470A performance verification')
        self.assertTrue(twin.set_standard(s.idx, '5522A'))
        self.assertEqual(self.model.record(by='x', when='w'), twin.record(by='x', when='w'))
        QTest.mouseClick(w.btn_reset, Qt.MouseButton.LeftButton)
        pump()
        self.assertEqual(self.model.table(), before)
        self.assertEqual(w.pills['Standard changed'].text(), '0 changed')
        self.assertFalse(w.btn_reset.isEnabled())

    def test_bulk_change_by_checkboxes_and_apply(self):
        w = self.window()
        free = self.free_rows(n=2)
        self.assertEqual(len(free), 2)
        for i in free:
            click(w, i, 'pick')
        self.assertEqual(sorted(w.selected_indexes()), sorted(free))
        self.assertTrue(w.bulk_box.isEnabled())
        labels = [w.bulk_box.itemText(k) for k in range(w.bulk_box.count())]
        self.assertEqual(labels, [M.label(k) for k in self.model.common_options(free)])
        self.assertGreaterEqual(len(labels), 2)
        self.assertEqual(w.bulk_box.currentIndex(), -1, 'no standard is preselected')
        QTest.mouseClick(w.btn_apply, Qt.MouseButton.LeftButton)
        pump()
        self.assertEqual(self.model.counts()['changed'], 0, 'Apply with nothing chosen does nothing')
        w.bulk_box.setCurrentText(M.label(self.other(free[0])))
        QTest.mouseClick(w.btn_apply, Qt.MouseButton.LeftButton)
        pump()
        self.assertEqual(self.model.counts()['changed'], 2)
        self.assertTrue(all(self.model.rows[i].changed for i in free))
        self.assertEqual(w.pills['Standard changed'].text(), '2 changed')
        # filters
        w.set_filter('Changed by me')
        self.assertEqual(w.table.row_count()[0], 2)
        self.assertEqual(sorted(r.spec.idx for r in w.table.visible_rows()), sorted(free))
        w.set_filter('Needs attention')
        self.assertEqual(w.table.row_count()[0], self.model.counts()['attention'])
        w.set_filter('All')
        self.assertEqual(w.table.row_count()[0], len(self.model.rows))
        self.assertIn('Changed by me', w.filter_bar._buttons['Changed by me'].text())

    def test_ctrl_click_selection_still_selects_rows_for_the_bulk_change(self):
        w = self.window()
        free = self.free_rows(n=3)
        w.table.select_rows([self.model.rows[i] for i in free])
        pump()
        self.assertEqual(sorted(w.selected_indexes()), sorted(free))
        self.assertTrue(w.bulk_box.isEnabled())
        self.assertEqual(w.table.source_model.columns[0].value(self.model.rows[free[0]]), True, 'the check box mirrors the selection')

    def test_reported_never_below_the_scope_minimum_whatever_is_chosen(self):
        w = self.window()
        free = self.free_rows()
        w.table.select_rows([self.model.rows[i] for i in free])
        pump()
        for std in ('5522A', '5560A'):
            w.bulk_box.setCurrentText(M.label(std)) if std in [M.key_of(w.bulk_box.itemText(k)) for k in range(w.bulk_box.count())] else None
            QTest.mouseClick(w.btn_apply, Qt.MouseButton.LeftButton)
            pump()
            for r in self.model.rows:
                if r.cur.cmc is not None and r.cur.reported is not None:
                    self.assertGreaterEqual(r.cur.reported, r.cur.cmc * (1 - 1e-12), (r.spec.step, std))
                self.assertEqual(cell_texts(w, r.spec.idx), tk_row_values(r))
        raised = [r for r in self.model.rows if r.status == M.RAISED]
        self.assertTrue(raised, 'some points sit at the scope minimum')
        for r in raised:
            self.assertEqual(cell_texts(w, r.spec.idx)[8], M.RAISED)
            self.assertEqual(r.cur.reported, r.cur.cmc if r.cur.cmc is not None and r.cur.reported <= r.cur.cmc * (1 + 1e-9) else r.cur.reported)

    def test_default_standard_moves_every_row_without_its_own_choice(self):
        w = self.window()
        w.default_box.setCurrentText('Fluke 5522A')
        w.on_default()
        self.assertEqual(self.model.default_std, '5522A')
        moved = [r for r in self.model.rows if r.changed]
        self.assertTrue(moved)
        self.assertTrue(all(r.standard == '5522A' for r in moved))
        self.assertEqual(w.default_box.currentText(), 'Fluke 5522A')
        QTest.mouseClick(w.btn_reset, Qt.MouseButton.LeftButton)
        pump()
        self.assertEqual(self.model.default_std, '5560A')
        self.assertEqual(w.default_box.currentText(), 'Fluke 5560A')

    def test_no_uncertainty_required_and_locked_rows_have_no_drop_down(self):
        w = self.window()
        nou = [r for r in self.model.rows if r.cur.status == M.NO_UNC]
        locked = [r for r in self.model.rows if r.spec.locked]
        self.assertTrue(nou and locked)
        for r in nou:
            self.assertTrue(r.spec.locked)
            ix = click(w, r.spec.idx, 'std')
            self.assertFalse(isinstance(w.table.indexWidget(ix), QComboBox), 'a locked row opens nothing')
            self.assertFalse(r.changed)
        self.assertEqual(w.pills.get(M.NO_UNC), None)
        w.set_filter('Needs attention')
        self.assertFalse(any(r.cur.status == M.NO_UNC for r in w.table.visible_rows()))
        freq = [r for r in locked if r.spec.q.get('kind') == 'FREQ']
        for r in freq:
            self.assertEqual(cell_texts(w, r.spec.idx)[3], M.LOCKED_FREQUENCY)
            self.assertFalse(self.model.set_standard(r.spec.idx, '5522A'))

    def test_demo_run_is_marked(self):
        core.DEMO_SUFFIX = ' [DEMO]'
        try:
            w = self.window(demo=True)
            self.assertIn('[DEMO]', w.windowTitle())
            self.assertIn('DEMO DATA - NOT CALIBRATION EVIDENCE', w.demo_banner.text_label.text())
            self.assertTrue(w.demo_banner.isVisible())
        finally:
            core.DEMO_SUFFIX = ''
        w2 = self.window()
        self.assertFalse(hasattr(w2, 'demo_banner'))

    def test_narrow_window_keeps_everything_visible(self):
        w = self.window()
        w.resize(900, 600)
        pump()
        for name in ('btn_ok', 'btn_reset', 'btn_cancel', 'bulk_box', 'default_box', 'btn_apply', 'btn_standards'):
            b = getattr(w, name)
            r = b.mapTo(w, QPoint(0, 0))
            self.assertTrue(b.isVisible() and r.x() >= 0 and r.x() + b.width() <= w.width() and r.y() + b.height() <= w.height(), name)
        self.assertTrue(w._pills_below)
        w.resize(1360, 860)
        pump()
        self.assertFalse(w._pills_below)

    def test_standards_used_dialog_is_kept_with_the_details(self):
        w = self.window()
        seen = {}

        def drive():
            dlg = QApplication.activeModalWidget()
            seen['title'] = dlg.title_label.text()
            edits = dlg.findChildren(QLineEdit)
            seen['n'] = len(edits)
            edits[0].setText('Fluke 5560A')
            edits[1].setText('S5560')
            edits[2].setText('2027-01-01')
            dlg.button('ok').click()
        QTimer.singleShot(50, drive)
        w.edit_standards()
        self.assertEqual(seen, {'title': 'Standards used (kept with the report record; optional)', 'n': 9})
        self.assertEqual(w.standards[0], {'description': 'Fluke 5560A', 'serial': 'S5560', 'due': '2027-01-01'})
        self.assertEqual(w.details()['standards'][0]['serial'], 'S5560')
        QTimer.singleShot(50, lambda: QApplication.activeModalWidget().button('cancel').click())
        w.edit_standards()
        self.assertEqual(w.standards[0]['serial'], 'S5560', 'Cancel keeps what was there')


# =====================================================================================================================  not in scope: typed uncertainty
@unittest.skipUnless(READY, WHY)
class NotInScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = get_app()

    def setUp(self):
        self.root = QWidget()
        self.addCleanup(self.root.deleteLater)
        self.model = M.ReviewModel([T.oos_spec()], '5560A', asset='A-1', procedure='x')
        self.w = RR.ReviewWindow(self.root, self.model, 'x')
        self.addCleanup(self.w.deleteLater)
        self.w.show()
        self.w.resize(1360, 700)
        pump()

    def editor(self):
        ix = click(self.w, 0, 'reported')
        ed = self.w.table.indexWidget(ix)
        self.assertIsInstance(ed, QLineEdit)
        return ix, ed

    def type_in(self, ed, text):
        ed.clear()
        QTest.keyClicks(ed, text)
        QTest.keyClick(ed, Qt.Key.Key_Return)
        pump(4)

    def test_the_row_is_red_with_a_hint_and_a_type_cell(self):
        w = self.w
        row = self.model.rows[0]
        self.assertEqual(row.status, M.NOT_IN_SCOPE)
        self.assertEqual(w.pills['Not in scope'].text(), '1 not in scope')
        self.assertIn('1 point(s) not in the lab scope (red): printed as before. Click the Reported cell [type] to enter an uncertainty.', w.hint_text())
        self.assertTrue(cell_texts(w, 0)[6].endswith('[type]'))
        w.set_filter('Needs attention')
        self.assertEqual(w.table.row_count()[0], 1)

    def test_typed_value_is_kept_cleared_and_recorded(self):
        w = self.w
        ix, ed = self.editor()
        self.assertIn('Type the uncertainty (k = 2) for step 9-9, for example 3.5 mV', w.hint_text())
        self.type_in(ed, 'junk')
        row = self.model.rows[0]
        self.assertIsNone(row.typed, 'a bad entry is refused')
        self.assertNotEqual(w.hint_text(), '')
        self.assertNotIn('Type the uncertainty', w.hint_text(), 'the message says what is wrong')
        ed2 = w.table.indexWidget(ix)
        self.assertIsInstance(ed2, QLineEdit, 'the editor stays open with the text for another try')
        self.assertEqual(ed2.text(), 'junk')
        self.type_in(ed2, '3.5 mV')
        self.assertIsNotNone(row.typed)
        self.assertEqual(row.status, M.MANUAL)
        self.assertEqual(row.typed['display'], '3.5 mV')
        self.assertEqual(w.pills[M.MANUAL].text(), '1 manual')
        self.assertEqual(cell_texts(w, 0)[6], '3.5 mV')
        self.assertEqual(cell_texts(w, 0)[8], M.MANUAL)
        # clear it: an empty entry returns to the engine's value
        ix, ed = self.editor()
        self.assertEqual(ed.text(), '3.5 mV')
        self.type_in(ed, '')
        self.assertIsNone(row.typed)
        self.assertEqual(row.status, M.NOT_IN_SCOPE)
        # Esc leaves the cell as it was
        ix, ed = self.editor()
        QTest.keyClicks(ed, '9 mV')
        QTest.keyClick(ed, Qt.Key.Key_Escape)
        pump(4)
        self.assertIsNone(row.typed)
        self.assertIn('not in the lab scope', w.hint_text())
        # a focus change does not keep it either (the Tk editor was only closed)
        ix, ed = self.editor()
        QTest.keyClicks(ed, '9 mV')
        self.w.btn_cancel.setFocus(Qt.FocusReason.TabFocusReason)
        pump(4)
        self.assertIsNone(row.typed)
        # the record carries the value, who and when
        ix, ed = self.editor()
        self.type_in(ed, '3.5 mV')
        block = M.review_block([self.model], by='T. Tech', when='2026-10-24T10:00:00')
        ch = block['reviews'][0]['changes'][0]
        self.assertEqual((ch['manual'], ch['manual_value'], ch['manual_text'], ch['entered_by'], ch['status']), (True, 0.0035, '3.5 mV', 'T. Tech', M.MANUAL))

    def test_a_row_the_scope_covers_does_not_open_a_text_editor(self):
        app, _t = T.truevolt_app()
        specs, default = M.specs_for(app)
        model = M.ReviewModel(specs, default)
        w = RR.ReviewWindow(self.root, model, 'x')
        self.addCleanup(w.deleteLater)
        w.show()
        w.resize(1360, 860)
        pump()
        ins = next(r.spec.idx for r in model.rows if not r.spec.locked and not r.can_type())
        ix = click(w, ins, 'reported')
        self.assertFalse(isinstance(w.table.indexWidget(ix), QLineEdit))

    def test_enter_on_a_row_opens_its_drop_down(self):
        w = self.w
        w.table.select_rows([self.model.rows[0]])
        w.table.setCurrentIndex(cell(w, 0, 'step'))
        pump()
        w._activate(self.model.rows[0])
        pump()
        self.assertIsInstance(w.table.indexWidget(cell(w, 0, 'std')), QComboBox)


# =====================================================================================================================  ask(): Generate / Cancel, the stored record
def run_in_modal(drive, delay=30):
    """Run `drive()` once the modal window of the call that follows is up (exec() blocks the caller)."""
    errors = []

    def go():
        try:
            drive()
        except Exception as exc:                                    # noqa: BLE001
            import traceback
            traceback.print_exc()
            errors.append(exc)
            w = RR.ReviewWindow.last
            if w is not None:
                w.cancel()
    QTimer.singleShot(delay, go)
    return errors


@unittest.skipUnless(READY, WHY)
class Ask(Base):
    def setUp(self):
        super().setUp()
        self.root = QMainWindow()
        self.addCleanup(self.root.deleteLater)
        self.app.root = self.root
        self.addCleanup(setattr, self.app, 'root', mock.MagicMock())

    def test_generate_returns_the_details_and_the_review_record(self):
        free = self.free_rows(n=2)
        chosen = {}

        def drive():
            w = RR.ReviewWindow.last
            w.resize(1360, 860)
            pump()
            w.fields['technician'].setText('  Mike ')
            w.fields['temperature'].setText('22.4 C')
            w.fields['humidity'].setText('41 %RH')
            w.tar.setChecked(True)
            for i in free:
                ix = click(w, i, 'std')
                pick_in_combo(w, ix, M.label(self.other(i)))
                chosen[i] = w.model.rows[i].standard
            self.assertEqual(w.model.counts()['changed'], 2)
            QTest.mouseClick(w.btn_ok, Qt.MouseButton.LeftButton)
        errors = run_in_modal(drive)
        details = RR.ask(self.root, 'Keysight 34470A performance verification', app=self.app)
        self.assertEqual(errors, [])
        self.assertIsInstance(details, dict)
        self.assertEqual((details['technician'], details['temperature'], details['humidity']), ('Mike', '22.4 C', '41 %RH'))
        self.assertEqual(details['procedure'], 'Keysight 34470A performance verification')
        self.assertEqual((details['show_tar'], details['show_tur']), (True, False))
        self.assertEqual(details['show_tar_tur'], report_pdf.TarTur(True, False))
        self.assertEqual(sorted(details), sorted(['technician', 'temperature', 'humidity', 'standards', 'procedure', 'show_tar', 'show_tur', 'show_tar_tur', 'uncertainty_review']))
        rev = details['uncertainty_review']
        self.assertEqual((rev['version'], len(rev['reviews'])), (1, 1))
        # identical to the record of the toolkit-free model replayed without any window
        twin = M.ReviewModel(self.specs, self.default, asset='A-100', procedure='Keysight 34470A performance verification')
        for i, std in chosen.items():
            twin.set_standard(i, std)
        want = twin.record(by='Mike', when='X')
        got = rev['reviews'][0]
        self.assertEqual(got, want)
        self.assertEqual(got['changed'], 2)
        self.assertEqual({c['idx'] for c in got['changes']}, set(free))
        s = core.Settings('report_details')
        self.assertEqual((s.get('technician'), s.get('temperature')), ('Mike', '22.4 C'), 'remembered for next time')
        self.assertEqual(report_pdf.remembered_show_tar_tur().tar, True)

    def test_cancel_and_escape_return_none(self):
        errors = run_in_modal(lambda: QTest.mouseClick(RR.ReviewWindow.last.btn_cancel, Qt.MouseButton.LeftButton))
        self.assertIsNone(RR.ask(self.root, 'x', app=self.app))
        self.assertEqual(errors, [])
        errors = run_in_modal(lambda: QTest.keyClick(RR.ReviewWindow.last, Qt.Key.Key_Escape))
        self.assertIsNone(RR.ask(self.root, 'x', app=self.app))
        self.assertEqual(errors, [])

    def test_the_engine_is_found_by_its_root_and_an_unknown_parent_falls_back(self):
        self.assertIs(RR.find_app(self.root), self.app)
        stranger = QWidget()
        self.assertIsNone(RR.find_app(stranger))
        self.assertIs(RR.ask(stranger, 'x'), RR.UNAVAILABLE)
        self.assertIs(RR.UNAVAILABLE, F.UNAVAILABLE)
        with mock.patch.object(RD, 'ask_details_plain', return_value={'plain': 1}) as plain:
            self.assertEqual(RD.ask_details(stranger, 'p'), {'plain': 1})
        plain.assert_called_once_with(stranger, 'p')
        with mock.patch.object(RD, 'USE_REVIEW', False), mock.patch.object(RR, 'ask') as review, mock.patch.object(RD, 'ask_details_plain', return_value={'plain': 2}):
            self.assertEqual(RD.ask_details(self.root, 'p'), {'plain': 2})
        review.assert_not_called()

    def test_ask_details_reaches_the_review_through_the_report_dialog_switch(self):
        """report_dialog.ask_details(parent) with a Qt parent is the Qt entry (the call every engine makes); a Tk-like parent is not."""
        self.assertTrue(report_dialog._is_qt(self.root))
        self.assertTrue(report_dialog._is_qt(QWidget()))
        for other in (None, object(), mock.MagicMock(), 'root'):
            self.assertFalse(report_dialog._is_qt(other))
        errors = run_in_modal(lambda: (RR.ReviewWindow.last.fields['technician'].setText('Via switch'), RR.ReviewWindow.last.btn_ok.click()))
        details = report_dialog.ask_details(self.root, 'Keysight 34470A performance verification')
        self.assertEqual(errors, [])
        self.assertEqual(details['technician'], 'Via switch')
        self.assertIn('uncertainty_review', details)
        with mock.patch.object(RD, 'ask_details') as qt:
            with mock.patch.object(report_dialog, 'USE_REVIEW', False), mock.patch.object(report_dialog, 'ask_details_plain', return_value={'tk': 1}) as tk_plain:
                self.assertEqual(report_dialog.ask_details(object(), 'x'), {'tk': 1})
        qt.assert_not_called()
        tk_plain.assert_called_once()
        with mock.patch.object(RD, 'ask_details', return_value={'qt': 1}) as qt:
            self.assertEqual(report_dialog.ask_details(self.root, 'x'), {'qt': 1})
        qt.assert_called_once_with(self.root, 'x')


# =====================================================================================================================  the report path: PDF, snapshot, Regenerate
@unittest.skipUnless(READY, WHY)
class ReportPath(Base):
    def setUp(self):
        super().setUp()
        self.dir = Path(tempfile.mkdtemp())
        ctx = R.registry()
        self.db = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.root = QMainWindow()
        self.addCleanup(self.root.deleteLater)

    def review(self, app, change=0):
        """Open the Qt review for `app`, change `change` rows through the cell editors, Generate; return the details dict."""
        app.root = self.root

        def drive():
            w = RR.ReviewWindow.last
            w.resize(1360, 860)
            pump()
            done = 0
            for r in w.model.rows:
                if done >= change:
                    break
                if r.spec.locked or r.cur.status in (M.NOT_IN_SCOPE, M.NO_UNC) or '5522A' not in w.model.options(r.spec.idx) or r.spec.default_std == '5522A':
                    continue
                if not r.cur.unc_text:
                    continue
                pick_in_combo(w, click(w, r.spec.idx, 'std'), 'Fluke 5522A')
                done += 1
            w.fields['technician'].setText(R.DETAILS['technician'])
            w.fields['temperature'].setText(R.DETAILS['temperature'])
            w.fields['humidity'].setText(R.DETAILS['humidity'])
            w.btn_ok.click()
        errors = run_in_modal(drive)
        details = RR.ask(self.root, 'bench test', app=app)
        self.assertEqual(errors, [])
        details['standards'] = R.DETAILS['standards']
        return details

    def test_no_change_gives_the_same_pdf_as_before(self):
        app, mod = T.truevolt_app()
        a, b = self.dir / 'a.pdf', self.dir / 'b.pdf'
        T.export(app, mod, a, R.DETAILS)
        details = self.review(app, change=0)
        self.assertEqual(details['uncertainty_review']['reviews'][0]['changed'], 0)
        T.export(app, mod, b, dict(R.DETAILS, uncertainty_review=details['uncertainty_review']))
        self.assertEqual(R.differences(a, b, None), [])

    def test_changed_standard_prints_persists_and_regenerates_identically(self):
        app, mod = T.truevolt_app()
        base = self.dir / 'base.pdf'
        T.export(app, mod, base, R.DETAILS)
        rows_before = app.certificate_rows()
        details = self.review(app, change=3)
        rev = details['uncertainty_review']['reviews'][0]
        self.assertEqual(rev['changed'], 3)
        out = self.dir / 'changed.pdf'
        T.export(app, mod, out, dict(R.DETAILS, uncertainty_review=details['uncertainty_review'], show_tar_tur=report_pdf.TarTur(True, True)))
        rid = R.last_run_id('A-100')
        snap = rs.load(rid)
        self.assertEqual(snap.status, rs.OK)
        changes = {c['idx']: c for c in rev['changes']}
        for i, row in enumerate(snap.data['rows']):
            if i in changes:
                self.assertEqual(row['Uncertainty'], changes[i]['uncertainty'])
                self.assertEqual(row['TUR'], changes[i]['tur'])
            else:
                self.assertEqual(row['Uncertainty'], rows_before[i]['Uncertainty'])
        self.assertTrue(any(snap.data['rows'][i]['Uncertainty'] != rows_before[i]['Uncertainty'] for i in changes))
        self.assertEqual(snap.data['details']['uncertainty_review']['reviews'][0]['changed'], 3)
        again = self.dir / 'again.pdf'
        res = T.regenerate(rid, again)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(R.differences(out, again, None), [], 'Regenerate PDF reprints the changed standard unchanged')
        self.assertNotEqual(R.pdf_text(out), R.pdf_text(base))

    def test_the_qt_record_prints_the_same_pdf_as_the_tk_model_record(self):
        """The record the Qt window stores and the one the model builds directly for the same choices print the same report (Tk-driven = Qt-driven)."""
        app, mod = T.truevolt_app()
        details = self.review(app, change=3)
        twin = M.ReviewModel(*M.specs_for(app)[:1], M.specs_for(app)[1], asset='A-100', procedure='bench test')
        for c in details['uncertainty_review']['reviews'][0]['changes']:
            twin.set_standard(c['idx'], c['standard'])
        a, b = self.dir / 'qt.pdf', self.dir / 'model.pdf'
        T.export(app, mod, a, dict(R.DETAILS, uncertainty_review=details['uncertainty_review']))
        T.export(app, mod, b, dict(R.DETAILS, uncertainty_review=M.review_block([twin], by=R.DETAILS['technician'])))
        self.assertEqual(R.differences(a, b, None), [])

    def test_demo_report_is_marked_and_not_recorded(self):
        app, mod = T.truevolt_app(demo=True)
        details = self.review(app, change=1)
        out = self.dir / 'demo.pdf'
        T.export(app, mod, out, dict(R.DETAILS, uncertainty_review=details['uncertainty_review']))
        self.assertIn('NOT CALIBRATION EVIDENCE', R.pdf_text(out))
        self.assertIsNone(R.last_run_id('A-100'))

    def test_typed_uncertainty_prints_and_regenerates(self):
        s = T.oos_spec()
        rows = [report_pdf.cert_row('AC 1000 V range', 1000.0, 999.0, 1001.0, 'V', reading=1000.1, section='AC volts', uncertainty='760 mV')]
        rows[0]['Nominal'] = '1000 V @ 10 Hz'
        spec = M.PointSpec(0, '9-9', 'AC volts', rows[0]['Description'], rows[0]['Nominal'], s.q, s.q, 999.0, 1001.0, 'V', '5560A', printed=dict(Uncertainty='760 mV'))
        model = M.ReviewModel([spec], '5560A', asset='A-77', procedure='x')

        def drive():
            w = RR.ReviewWindow.last
            w.resize(1360, 700)
            pump()
            ed = w.table.indexWidget(click(w, 0, 'reported'))
            ed.selectAll()
            QTest.keyClicks(ed, '3.5 mV')
            QTest.keyClick(ed, Qt.Key.Key_Return)
            pump(4)
            w.fields['technician'].setText('T. Tech')
            w.btn_ok.click()
        errors = run_in_modal(drive)
        with mock.patch.object(RR, 'build_models', return_value=([model], False)):
            details = RR.ask(self.root, 'x')
        self.assertEqual(errors, [])
        ch = details['uncertainty_review']['reviews'][0]['changes'][0]
        self.assertEqual((ch['manual'], ch['manual_text'], ch['entered_by'], ch['status']), (True, '3.5 mV', 'T. Tech', M.MANUAL))
        pdf = self.dir / 'm.pdf'
        report_pdf.write_calibration_pdf(str(pdf), rows, header=[('Instrument', 'X'), ('Instrument ID', 'A-77'), ('Serial', '1')],
                                         details=dict(R.DETAILS, uncertainty_review=details['uncertainty_review']))
        text = R.pdf_text(pdf)
        self.assertIn('3.5 mV', text)
        self.assertNotIn('760 mV', text)
        rid = T.labregistry.runs_for('A-77')[0]['id']
        self.assertEqual(rs.load(rid).data['rows'][0]['Uncertainty'], '3.5 mV')
        again = self.dir / 'm2.pdf'
        self.assertTrue(T.regenerate(rid, again).ok)
        self.assertEqual(R.differences(pdf, again, None), [])


# =====================================================================================================================  the phase 2 engines open the same window
@unittest.skipUnless(READY, WHY)
class Phase2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = get_app()

    def test_every_engine_builds_a_window_whose_rows_equal_the_model(self):
        import test_reprint_review_phase2 as P2
        root = QWidget()
        self.addCleanup(root.deleteLater)
        want = {'ws': (0, 36), 'mdo': (19, 21), 'fgen': (42, 1), 'tds': (1, 3)}
        for name in P2.BUILDERS:
            app, _mod = P2.built(name)
            specs, default = M.specs_for(app)
            model = M.ReviewModel(specs, default, asset=F.asset_of(app))
            w = RR.ReviewWindow(root, model, f'{name} performance verification')
            w.show()
            w.resize(1360, 860)
            pump()
            c = model.counts()
            self.assertEqual((c[M.NOT_IN_SCOPE], c[M.NO_UNC]), want[name], name)
            self.assertEqual(w.table.row_count(), (len(model.rows),) * 2, name)
            self.assertEqual(w.pills['Not in scope'].text(), f'{want[name][0]} not in scope', name)
            for r in model.rows:
                self.assertEqual(cell_texts(w, r.spec.idx), tk_row_values(r), (name, r.spec.step))
            w.set_filter('Needs attention')
            self.assertEqual(w.table.row_count()[0], c['attention'], name)
            w.deleteLater()


# =====================================================================================================================  the run queue: one review per meter, in order
@unittest.skipUnless(READY, WHY)
class Queue(unittest.TestCase):
    pass


if READY:
    import test_beta_run_queue as Q

    def setUpModule():
        Q.setUpModule()

    class FakeWindow:
        made = []

        def __init__(self, parent, model, procedure='', demo=False, details=None, position=(1, 1)):
            self.model, self.position, self.prior = model, position, details
            FakeWindow.made.append(self)

        def run(self):
            m = self.model
            free = [(i, [k for k in m.options(i) if k != r.spec.default_std]) for i, r in enumerate(m.rows) if not r.spec.locked and len(m.options(i)) > 1]
            if self.position[0] == 1 and free:
                m.set_standard(free[0][0], free[0][1][0])
            d = dict(technician='T', temperature='23', humidity='45', standards=[], procedure=self.model.procedure, show_tar=False, show_tur=True)
            d['show_tar_tur'] = report_pdf.TarTur(False, True)
            return d

    class Queue(Q.EngineBase):                                    # noqa: F811
        def setUp(self):
            super().setUp()
            import uuid
            tag = uuid.uuid4().hex[:6]
            self.A = tuple(f'{tag}-{n}' for n in (1, 2, 3))
            FakeWindow.made = []
            get_app()

        def test_one_qt_review_per_meter_in_sequence_and_each_meter_keeps_its_own_record(self):
            app = self.real(assets=self.A)
            self.hn.run_all()
            with mock.patch.object(RR, 'ReviewWindow', FakeWindow):
                d = RD.ask_details(app.root, 'x')
            self.assertEqual([w.position for w in FakeWindow.made], [(1, 1)] if not app.__dict__.get('_review_all_meters') else [(1, 3), (2, 3), (3, 3)])
            self.assertEqual(len(d['uncertainty_review']['reviews']), len(FakeWindow.made))
            FakeWindow.made = []
            app.__dict__['_review_all_meters'] = True
            try:
                with mock.patch.object(RR, 'ReviewWindow', FakeWindow):
                    d = RD.ask_details(app.root, 'x')
            finally:
                app.__dict__.pop('_review_all_meters', None)
            self.assertEqual([w.position for w in FakeWindow.made], [(1, 3), (2, 3), (3, 3)])
            self.assertEqual([w.model.asset for w in FakeWindow.made], list(self.A))
            self.assertEqual([r['asset'] for r in d['uncertainty_review']['reviews']], list(self.A))
            self.assertEqual([r['changed'] for r in d['uncertainty_review']['reviews']], [1, 0, 0])


# =====================================================================================================================  the plain details popup
@unittest.skipUnless(READY, WHY)
class PlainDetails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = get_app()

    def setUp(self):
        self.root = QWidget()
        self.addCleanup(self.root.deleteLater)
        core.Settings('report_details').data.clear()
        for name in ('report_details.json', 'report_tartur.json'):
            p = Path.home() / '.calibration_suite' / name
            if p.exists():
                p.unlink()

    def drive(self, fn):
        errors = []

        def go():
            try:
                fn(QApplication.activeModalWidget())
            except Exception as exc:                            # noqa: BLE001
                errors.append(exc)
                QApplication.activeModalWidget().reject()
        QTimer.singleShot(40, go)
        return errors

    def fields(self, dlg):
        e = {x.accessibleName(): x for x in dlg.findChildren(QLineEdit)}
        return e

    def test_create_report_returns_the_tk_dict_and_remembers_it(self):
        def fill(dlg):
            f = self.fields(dlg)
            self.assertEqual(dlg.windowTitle(), 'Report details')
            f['Technician'].setText(' Mike ')
            f['Temperature'].setText('23.1 °C')
            f['Humidity'].setText('45 %RH')
            f['Standard (model) 1'].setText('Fluke 5560A')
            f['Serial number 1'].setText('S5560')
            f['Calibration due 1'].setText('2027-01-01')
            from PySide6.QtWidgets import QCheckBox
            boxes = {b.text(): b for b in dlg.findChildren(QCheckBox)}
            self.assertEqual(sorted(boxes), ['Show TAR on the data file', 'Show TUR on the data file'])
            boxes['Show TUR on the data file'].setChecked(True)
            QTest.keyClick(f['Humidity'], Qt.Key.Key_Return)             # Enter = Create report (the Tk dialog bound <Return>)
        errors = self.drive(fill)
        d = RD.ask_details_plain(self.root, 'Fluke 117 performance verification')
        self.assertEqual(errors, [])
        self.assertEqual(sorted(d), ['humidity', 'procedure', 'show_tar', 'show_tar_tur', 'show_tur', 'standards', 'technician', 'temperature'])
        self.assertEqual((d['technician'], d['temperature'], d['humidity']), ('Mike', '23.1 °C', '45 %RH'))
        self.assertEqual(d['procedure'], 'Fluke 117 performance verification')
        self.assertEqual(d['standards'], [{'description': 'Fluke 5560A', 'serial': 'S5560', 'due': '2027-01-01'}, {'description': '', 'serial': '', 'due': ''},
                                          {'description': '', 'serial': '', 'due': ''}])
        self.assertEqual((d['show_tar'], d['show_tur']), (False, True))
        self.assertEqual(d['show_tar_tur'], report_pdf.TarTur(False, True))
        self.assertTrue(d['show_tar_tur'])
        s = core.Settings('report_details')
        self.assertEqual((s.get('technician'), s.get('standards')[0]['serial']), ('Mike', 'S5560'))
        self.assertEqual(report_pdf.remembered_show_tar_tur(), report_pdf.TarTur(False, True))
        # the next time the entries are there
        seen = {}

        def look(dlg):
            f = self.fields(dlg)
            seen.update(tech=f['Technician'].text(), serial=f['Serial number 1'].text())
            dlg.button('cancel').click()
        self.drive(look)
        self.assertIsNone(RD.ask_details_plain(self.root, 'x'))
        self.assertEqual(seen, {'tech': 'Mike', 'serial': 'S5560'})

    def test_cancel_and_escape_return_none_and_remember_nothing(self):
        def fill(dlg):
            self.fields(dlg)['Technician'].setText('Nobody')
            dlg.button('cancel').click()
        self.drive(fill)
        self.assertIsNone(RD.ask_details_plain(self.root, 'x'))
        self.drive(lambda dlg: QTest.keyClick(dlg, Qt.Key.Key_Escape))
        self.assertIsNone(RD.ask_details_plain(self.root, 'x'))
        self.assertEqual(core.Settings('report_details').get('technician'), None)

    def test_demo_title(self):
        core.DEMO_SUFFIX = ' [DEMO]'
        try:
            titles = []
            self.drive(lambda dlg: (titles.append(dlg.windowTitle()), dlg.button('cancel').click()))
            RD.ask_details_plain(self.root, 'x')
        finally:
            core.DEMO_SUFFIX = ''
        self.assertEqual(titles, ['Report details [DEMO]'])


if __name__ == '__main__':
    unittest.main()
