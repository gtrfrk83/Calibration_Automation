"""Procedure Generator tab (qtui/screens/procedure_generator.py + procedure_generator_review.py), offscreen.  The Claude API client is a mock; every dialog is patched.
Run:  python -m unittest tests.test_qt_procedure_generator"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

import pg_fixtures as fx  # noqa: E402
import procedure_generator as pg  # noqa: E402
import generated_draft as gd  # noqa: E402

if HAVE_QT:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from qtui import app, theme
    from qtui.screens import procedure_generator as G
    from qtui.screens import procedure_generator_review as R


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class PanelCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.create_app()

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.d / 'data'), 'HOME': str(self.d / 'home'), 'USERPROFILE': str(self.d / 'home'), 'ANTHROPIC_API_KEY': 'sk-ant-api03-QTTESTKEY0123456789'})
        env.start()
        self.addCleanup(env.stop)
        self.reg = self.d / 'data' / 'lab_registry.sqlite3'
        self.store = pg.Store(root=self.d / 'gen', registry=self.reg)
        self.shown = []
        self.saved = []
        for name, ret in (('_info', None), ('_warn', None), ('_error', None)):
            p = mock.patch.object(G, name, lambda parent, title, text, detail='', _n=name: self.shown.append((_n, title, text, detail)))
            p.start()
            self.addCleanup(p.stop)
        self.answer = True
        p = mock.patch.object(G, '_ask', lambda *a, **k: self.answer)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(R, '_ask', lambda *a, **k: True)
        p.start()
        self.addCleanup(p.stop)
        self.client = fx.FakeClient([fx.FakeResponse(fx.good_items())])
        self.panel = G.ProcedureGeneratorPanel(store=self.store, on_saved=lambda: self.saved.append(1), client_factory=lambda key: self.client)
        self.panel.resize(1280, 800)
        self.panel.show()
        self.addCleanup(self.panel.close)
        self.pdf = fx.make_pdf(self.d / 'manual.pdf', 4)

    def new(self, mode=None, name='Meter', model='M100'):
        p = self.panel.new_project()
        self.panel.name_edit.setText(name)
        self.panel.make_edit.setText('Acme')
        self.panel.model_edit.setText(model)
        self.panel._save_fields()
        if mode:
            self.panel.set_mode(mode)
        return self.panel.p

    def reqs(self):
        return [(r.key, r.met) for r, _b in self.panel.requirement_rows]


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Modes(PanelCase):
    def test_empty_state_then_new_project(self):
        self.assertIs(self.panel.stack.currentWidget(), self.panel.empty)
        p = self.new()
        self.assertIs(self.panel.stack.currentWidget(), self.panel.project_page)
        self.assertEqual(self.panel.list.count(), 1)
        self.assertEqual(self.panel.build_btn.isEnabled(), False)
        self.assertIn('Choose how the procedure is automated', self.panel.build_label.text())
        self.assertEqual(p.mode, '')

    def test_three_mode_cards_and_what_each_needs(self):
        self.new()
        self.assertEqual(set(self.panel.mode_cards), {pg.MANUAL, pg.ONEWAY, pg.TWOWAY})
        for mode, keys in ((pg.MANUAL, ['name', 'model', 'mode', 'spec']), (pg.ONEWAY, ['name', 'model', 'mode', 'spec']),
                           (pg.TWOWAY, ['name', 'model', 'mode', 'spec', 'instruments', 'photo'])):
            QTest.mouseClick(self.panel.mode_cards[mode], Qt.MouseButton.LeftButton)
            self.assertEqual(self.panel.p.mode, mode)
            self.assertEqual([k for k, _m in self.reqs()], keys, mode)
            self.assertTrue(self.panel.mode_cards[mode].selected if hasattr(self.panel.mode_cards[mode], 'selected') else True)
        self.assertTrue(self.panel.instrument_rows == [] and self.panel.add_instrument_btn is not None)

    def test_build_is_disabled_and_says_exactly_what_is_missing(self):
        self.new(pg.TWOWAY)
        self.assertFalse(self.panel.build_btn.isEnabled())
        self.assertIn('Spec sheet or manual', self.panel.build_label.text())
        self.assertIn('Hook-up photo', self.panel.build_label.text())
        self.panel.add_instrument('Acme M100', 'uut')
        self.assertIn('Programming manual (PDF) for Acme M100', self.panel.build_label.text())

    def test_twoway_complete_enables_build_which_explains_and_keeps_the_project(self):
        p = self.new(pg.TWOWAY)
        self.panel.add_files(pg.ROLE_SPEC, [self.pdf])
        ins = self.panel.add_instrument('Acme M100', 'uut')
        self.panel.add_files(pg.ROLE_PROG, [fx.make_pdf(self.d / 'prog.pdf', 2, 'Prog')], ins.id)
        self.panel.add_files(pg.ROLE_PHOTO, [fx.make_png(self.d / 'hook.png')])
        self.assertTrue(self.panel.build_btn.isEnabled())
        self.assertIn('coming', self.panel.build_btn.text().lower())
        res = self.panel.build()
        self.assertTrue(res.coming)
        self.assertEqual(self.shown[-1][0], '_info')
        self.assertIn('Two-way generation is coming', self.shown[-1][1])
        again = self.store.load(p.id)
        self.assertEqual((again.mode, len(again.files), len(again.instruments)), (pg.TWOWAY, 3, 1))
        self.assertEqual(self.saved, [])                                                   # nothing was built, nothing registered


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Uploads(PanelCase):
    def test_add_and_remove_files_with_hash_shown(self):
        p = self.new(pg.ONEWAY)
        added = self.panel.add_files(pg.ROLE_SPEC, [self.pdf])
        self.assertEqual(len(added), 1)
        t = self.panel.files_table
        self.assertEqual(t.rowCount(), 1)
        self.assertEqual(t.item(0, 0).text(), 'manual.pdf')
        self.assertEqual(t.item(0, 2).text(), '4')
        self.assertTrue(t.item(0, 4).toolTip() == added[0].sha256)
        self.assertIn('pages', self.panel.build_label.text())                               # the next thing needed: the table pages
        self.assertTrue(self.panel.remove_file(added[0].id))
        self.assertEqual(self.panel.files_table.rowCount(), 0)
        self.assertTrue(self.pdf.is_file())

    def test_a_bad_file_is_refused_with_a_message_and_nothing_is_stored(self):
        self.new(pg.MANUAL)
        bad = self.d / 'x.txt'
        bad.write_text('hi')
        self.assertEqual(self.panel.add_files(pg.ROLE_SPEC, [bad]), [])
        self.assertIn('must be PDF', self.panel.notice.text_label.text())
        self.assertEqual(self.panel.p.files, [])

    def test_the_text_is_never_read_as_html(self):
        self.new(pg.MANUAL)
        evil = self.d / '<b>bold<i>.txt'
        evil.write_text('hi')
        self.panel.add_files(pg.ROLE_SPEC, [evil])
        self.assertEqual(self.panel.notice.text_label.textFormat(), Qt.TextFormat.PlainText)

    def test_projects_persist_across_panels(self):
        p = self.new(pg.ONEWAY, name='Persisted')
        self.panel.add_files(pg.ROLE_SPEC, [self.pdf])
        other = G.ProcedureGeneratorPanel(store=pg.Store(root=self.d / 'gen', registry=self.reg))
        self.addCleanup(other.close)
        self.assertEqual(other.list.count(), 1)
        other.select_project(p.id)
        self.assertEqual((other.p.name, other.p.mode, len(other.p.files)), ('Persisted', pg.ONEWAY, 1))


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class ReviewAndBuild(PanelCase):
    def to_review(self, mode=pg.ONEWAY):
        self.new(mode)
        f = self.panel.add_files(pg.ROLE_SPEC, [self.pdf])[0]
        self.panel.open_review()
        rv = self.panel.review
        rv.run_sync = True
        rv.first_spin.setValue(1)
        rv.last_spin.setValue(1)
        rv.use_pages()
        return rv, f

    def test_read_review_accept_confirm_build_approve(self):
        rv, f = self.to_review()
        self.assertIs(self.panel.stack.currentWidget(), rv)
        self.assertFalse(rv.check_box.isEnabled())
        rv.read_pages()
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(rv.table.rowCount(), 3)
        self.assertEqual({r.status for r in rv.p.rows}, {pg.STATUS_CANDIDATE})
        self.assertIn('Nothing is accepted yet', rv.notice.text_label.text())
        self.assertFalse(self.panel.build_btn.isEnabled())
        rv.table.selectAll()
        rv._decide(pg.STATUS_ACCEPTED)
        self.assertEqual({r.status for r in rv.p.rows}, {pg.STATUS_ACCEPTED})
        self.assertTrue(rv.check_box.isEnabled())
        self.assertFalse(self.panel.build_btn.isEnabled())                                  # the page is not confirmed yet
        rv.check_box.setChecked(True)
        self.panel.close_review()
        self.assertTrue(self.panel.build_btn.isEnabled(), self.panel.build_label.text())
        res = self.panel.build()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(self.saved, [1])
        self.assertEqual(self.shown[-1][0], '_info')
        self.assertIn('DRAFT', self.shown[-1][1])
        self.assertEqual(self.panel.status_badge.text(), gd.DRAFT_TEXT)
        self.assertTrue(self.panel.approve_btn.isEnabled())
        self.assertFalse(self.panel.draft_btn.isEnabled())
        with mock.patch.object(G, '_ask_approval', lambda parent, name, who, unverified, sources=None: ('Owner Person', 'looks right')):
            st = self.panel.approve()
        self.assertFalse(st.draft)
        self.assertEqual(self.saved, [1, 1])
        self.assertIn('Approved by Owner Person', self.panel.status_badge.text())
        self.assertFalse(self.panel.approve_btn.isEnabled())
        self.assertTrue(self.panel.draft_btn.isEnabled())
        st = self.panel.mark_draft_again()
        self.assertTrue(st.draft)
        self.assertEqual([h[0] for h in gd.state(res.uid, self.reg).history], ['built', 'approve', 'draft_again'])

    def test_reading_without_a_key_says_so_and_rows_can_be_typed(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            rv, f = self.to_review()
            rv.read_pages()
            self.assertEqual(self.client.requests, [])
            self.assertIn('No API key', rv.notice.text_label.text())
            rv.add_row()
            self.assertEqual(rv.table.rowCount(), 1)
            self.assertEqual(rv.p.rows[0].source, 'typed')

    def test_a_failed_reading_shows_a_scrubbed_message_and_adds_nothing(self):
        class E(Exception):
            status_code = 400
            message = 'bad sk-ant-api03-QTTESTKEY0123456789'
        self.client.script = [E()]
        rv, f = self.to_review()
        rv.read_pages()
        self.assertEqual(rv.table.rowCount(), 0)
        self.assertNotIn('QTTESTKEY', rv.notice.text_label.text())
        self.assertIn('rejected', rv.notice.text_label.text())

    def test_editing_a_cell_marks_the_row_edited_and_unconfirms_the_page(self):
        rv, f = self.to_review()
        rv.read_pages()
        rv.table.selectAll()
        rv._decide(pg.STATUS_ACCEPTED)
        rv.check_box.setChecked(True)
        self.assertEqual(pg.gate(rv.p).stage, 'ready')
        col = [k for k, _t in R.COLUMNS].index('high')
        rv.table.item(0, col).setText('5.007 V')
        self.assertEqual(rv.p.rows[0].status, pg.STATUS_EDITED)
        self.assertFalse(rv.check_box.isChecked())
        self.assertEqual(pg.gate(rv.p).stage, 'unchecked')

    def test_rejected_rows_are_left_out(self):
        rv, f = self.to_review()
        rv.read_pages()
        rv.table.selectRow(0)
        rv._decide(pg.STATUS_REJECTED)
        rv.table.selectRow(1)
        rv.table.selectAll()
        for r in rv.p.rows:
            if r.status != pg.STATUS_REJECTED:
                pg.set_status(rv.p, r.id, pg.STATUS_ACCEPTED)
        pg.confirm_page(rv.p, f.id, 1)
        import procedure_generator_build as bd
        res = bd.build(rv.p, self.store, 'me', registry=self.reg, root=self.d / 'us')
        self.assertTrue(res.ok)
        self.assertEqual(res.points, 2)

    def test_manual_mode_offers_the_standard_choice_after_building(self):
        rv, f = self.to_review(pg.MANUAL)
        rv.read_pages()
        rv.table.selectAll()
        rv._decide(pg.STATUS_ACCEPTED)
        rv.check_box.setChecked(True)
        self.panel.close_review()
        res = self.panel.build()
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.kind, 'manual')
        self.assertFalse(self.panel.standard_box.isHidden())
        self.assertEqual(self.panel.standard_box.itemData(0), G.STANDARD_BEST)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class LooksOK(PanelCase):
    """Both themes and a large text scale: nothing is clipped to zero width and the window does not demand a wider screen."""

    def test_themes_and_text_scale(self):
        self.new(pg.TWOWAY)
        for name in ('light', 'dark'):
            try:
                theme.set_theme(name)
            except Exception:
                continue
            self.panel.refresh_project()
            self.panel.grab()
            self.assertLessEqual(self.panel.minimumSizeHint().width(), 1280)
        rv = R.ReviewPage(self.store, self.panel.p)
        self.addCleanup(rv.close)
        self.assertLessEqual(rv.minimumSizeHint().width(), 1280)


if HAVE_QT:
    import test_qt_manager as tqm
    import dsb_manager
    import procedure_generator_build as bd
    import procedure_generator_ai as ai

    class ManagerApproval(tqm.QtCase):
        """The owner's Approve / Mark as draft again from the Manager list (same dialog as the tab)."""

        def setUp(self):
            super().setUp()
            self.store = pg.Store()                                          # the (throw-away) data folder of test_qt_manager
            p = self.store.create('Listed job', 'me')
            p.make, p.model, p.mode = 'Acme', 'TM100', pg.ONEWAY
            f = self.store.add_file(p, fx.make_pdf(self.t / 'm.pdf'), pg.ROLE_SPEC)
            pg.set_pages(p, f.id, 1, 1)
            pg.add_rows(p, ai._parse_rows({'rows': fx.good_items()}, [(f.id, 1)], []))
            for r in p.rows:
                pg.set_status(p, r.id, pg.STATUS_ACCEPTED)
            pg.confirm_page(p, f.id, 1)
            res = bd.build(p, self.store, 'me')
            self.assertTrue(res.ok, res.message)
            self.uid = res.uid
            self.win.refresh()
            self.pump()
            self.asked = []
            self.answer = ('Owner Person', 'checked')
            q = mock.patch.object(G, '_ask_approval', lambda parent, name, who, unverified, sources=None: self.asked.append((name, who, list(unverified), dict(sources or {}))) or self.answer)
            q.start()
            self.addCleanup(q.stop)
            self.errors = []
            q = mock.patch.object(G, '_error', lambda parent, title, text: self.errors.append((title, text)))
            q.start()
            self.addCleanup(q.stop)
            self.confirm = True
            q = mock.patch.object(G, '_ask', lambda *a, **k: self.confirm)
            q.start()
            self.addCleanup(q.stop)

        def select_generated(self):
            row = next(r for r in self.win.table.rows() if r.iid == dsb_manager.IID_PREFIX + self.uid)
            self.win.table.select_rows([row])
            self.pump()
            return row

        def menu_texts(self):
            return [a.text() for a in self.win.build_row_menu().actions() if not a.isSeparator()]

        def test_a_draft_row_offers_approve_by_button_and_menu(self):
            row = self.select_generated()
            self.assertIn('DRAFT', row.status)
            self.assertFalse(self.win.btn_approve.isHidden())
            self.assertTrue(self.win.btn_draft_again.isHidden())
            self.assertIn('Approve (owner)...', self.menu_texts())
            self.assertNotIn('Mark as draft again...', self.menu_texts())

        def test_approving_from_the_list_uses_the_same_dialog_logs_and_clears_the_draft(self):
            self.select_generated()
            self.win.btn_approve.click()
            self.pump()
            name, who, unverified, sources = self.asked[0]
            self.assertIn('Listed job', name)
            self.assertTrue(unverified)                                       # the unverified list is shown
            self.assertTrue(sources)                                          # and the source files with their hashes
            st = gd.state(self.uid)
            self.assertFalse(st.draft)
            hist = st.history[-1]
            self.assertEqual((hist[0], hist[2], hist[4]), ('approve', 'Owner Person', 'checked'))
            row = self.select_generated()
            self.assertNotIn('DRAFT', row.status)
            self.assertTrue(self.win.btn_approve.isHidden())
            self.assertFalse(self.win.btn_draft_again.isHidden())
            self.assertIn('Mark as draft again...', self.menu_texts())
            self.assertIn('Approved by Owner Person', self.win.status.get())

        def test_cancelling_the_dialog_changes_nothing(self):
            self.select_generated()
            self.answer = None
            self.win.approve_generated()
            self.assertTrue(gd.state(self.uid).draft)
            self.answer = ('x', '')
            self.win.approve_generated()                                     # a one-letter name is refused by the record, not accepted
            self.assertTrue(gd.state(self.uid).draft)
            self.assertIn('name', self.errors[-1][1].lower())

        def test_mark_as_draft_again_from_the_list(self):
            self.select_generated()
            gd.approve(self.uid, 'Owner Person')
            self.select_generated()
            self.win.refresh_details()
            self.win.btn_draft_again.click()
            self.pump()
            self.assertTrue(gd.state(self.uid).draft)
            self.assertEqual(gd.state(self.uid).history[-1][0], 'draft_again')
            self.confirm = False
            gd.approve(self.uid, 'Owner Person')
            self.select_generated()
            self.win.draft_again_generated()
            self.assertFalse(gd.state(self.uid).draft)                       # declined: still approved

        def test_an_open_run_window_sees_the_approval(self):
            import dsb_run_harness as H
            import json
            import dsb_runtime as rt
            self.select_generated()
            spec = json.loads((rt.Path(dsb_manager.user_rows()[0]['spec_path'])).read_text())
            data = os.environ['CALSUITE_DATA']
            h = H.Harness().start()
            try:
                os.environ['CALSUITE_DATA'] = data                       # the run window reads the same registry as the Manager
                a = h.make_app(spec)
                self.assertTrue(a.generated_state().draft)
                self.win.approve_generated()
                self.assertFalse(a.generated_state().draft)
            finally:
                h.stop()

        def test_ordinary_procedures_never_get_the_action(self):
            self.select('Keithley 2000 Performance Verification')
            self.assertTrue(self.win.btn_approve.isHidden() and self.win.btn_draft_again.isHidden())
            self.assertFalse(any('Approve' in t or 'draft again' in t for t in self.menu_texts()))
            self.assertIsNone(self.win.approve_generated())
            self.assertIsNone(self.win.draft_again_generated())
            self.assertTrue(gd.state(self.uid).draft)


if __name__ == '__main__':
    unittest.main()
