"""Qt twins of the user-built datasheet runtime (QT-H): dsb_runtime_view_qt (section-mode bar, standards drawer, manual calibration window), dsb_override_view_qt (the typed
reading window) and dsb_prerun_view_qt (the pre-run list of unverified commands), reached through QtUiPort.

Headless (QT_QPA_PLATFORM=offscreen), skipped when PySide6 is not importable.

  * Golden prompts: the 12 scenarios of tests/golden_ui/ui_prompts_dsb.json and the 2 of ui_prompts_dsb_main.json (recorded from the Tk build before the port) through
    QtUiPort, the real Qt windows and a scripted operator: DMM, scope and generator sheets, manual run, HIGH VOLTAGE refusal, 'Measuring standard', the small dialogs, the
    launcher's open-file question and bad-spec error.
  * The windows: section-mode box (blank until a section is chosen, disabled while busy), the standards rows and their variables, the manual calibration window, the typed
    reading window (validation, the 'Use this reading?' confirmation, cancel) and the pre-run list (Cancel is the default, Accept is not).
"""
import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

try:
    import tkinter  # noqa: F401
    for _sub in ('messagebox', 'filedialog', 'simpledialog'):
        try:
            __import__('tkinter.' + _sub)
        except ImportError:
            pass
except ImportError:
    import _tk_stub
    _tk_stub.install()

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

GOLDEN = ROOT / 'tests' / 'golden_ui'

if HAVE_QT:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

    import dsb_fixtures as fx
    import dsb_override
    import dsb_override_view_qt as OV
    import dsb_prerun
    import dsb_prerun_view_qt as PV
    import dsb_runtime as rt
    import datasheet_builder_match as dm
    import datasheet_builder_specs as dsp
    import qt_handheld_harness as Q
    import ui_prompt_capture_dsb as D
    from qtui import app as qapp


def canon(obj):
    return json.loads(json.dumps(obj))


def spec_of(ds, **options):
    spec = dsp.export_spec(ds, plan=dm.match_datasheet(ds)).spec
    spec.setdefault('options', {}).update(options)
    return spec


def run_dialog(dlg, script, wait_ms=60):
    err = []

    def go():
        try:
            script(dlg)
        except BaseException as exc:                        # noqa: BLE001
            err.append(exc)
        if dlg.isVisible():
            dlg.reject()
    QTimer.singleShot(wait_ms, go)
    dlg.exec()
    if err:
        raise err[0]


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class GoldenPrompts(unittest.TestCase):
    def check(self, runner, fixture):
        want = json.loads((GOLDEN / fixture).read_text(encoding='utf-8'))
        got = canon(runner(lambda answers=None: Q.QtHarness(answers)))
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], f'{fixture}: scenario {scenario}')

    def test_user_datasheet_runs_12_scenarios(self):
        self.check(D._run_dsb, 'ui_prompts_dsb.json')

    def test_launcher_2_scenarios(self):
        self.check(D._run_dsb_main, 'ui_prompts_dsb_main.json')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class RuntimeWindow(unittest.TestCase):
    def setUp(self):
        self.hn = Q.QtHarness(None).start()

    def tearDown(self):
        self.hn.stop()

    def app(self, ds=None, **options):
        return self.hn.make_app(spec_of(ds or fx.generator_33220a_like(), **options), demo=True)

    def test_section_mode_box_is_blank_until_a_section_is_chosen_and_follows_busy(self):
        app = self.app()
        box = app.section_mode_box
        self.assertEqual(box.currentText(), '')
        self.assertFalse(box.isEnabled())
        self.assertEqual(app.section_caption.get(), 'Section mode: choose a section on the left')
        sec = list(app.section_mode)[0]
        app.pick_section(sec)
        QApplication.processEvents()
        self.assertTrue(box.isEnabled())
        self.assertEqual(box.currentText(), rt.rules.MODE_LABEL[app.section_mode[sec]])
        self.assertTrue(app.section_caption.get().startswith('Mode of "'))
        app.busy = True
        app._sync_mode_box()
        self.assertFalse(box.isEnabled())                       # the mode of a section cannot change while a run is active
        app.busy = False
        app._sync_mode_box()
        self.assertTrue(box.isEnabled())
        self.assertEqual([box.itemText(i) for i in range(box.count())], [rt.rules.MODE_LABEL[m] for m in app.allowed_modes()])

    def test_choosing_a_mode_switches_the_section_and_a_skipped_row_is_muted(self):
        app = self.app()
        sec = list(app.section_mode)[0]
        app.pick_section(sec)
        QApplication.processEvents()
        box = app.section_mode_box
        box.setCurrentIndex(box.findText(rt.rules.MODE_LABEL[rt.rules.SKIP]))
        box.activated.emit(box.currentIndex())
        QApplication.processEvents()
        self.assertEqual(app.section_mode[sec], rt.rules.SKIP)
        row = next(r for r in app.tree.rows() if app.by_id[r.iid]['section'] == sec)
        self.assertIn('skipped', row.tags)
        self.assertIn('not tested', row.values[-1])
        col = app.tree.source_model.columns[0]
        self.assertEqual(col.tone(row), 'muted')

    def test_standards_rows_are_bound_to_the_address_variables(self):
        app = self.app()
        needed = list(app.standards_needed())
        self.assertTrue(needed)
        edits = {e.accessibleName(): e for e in app.shell.drawer_body.findChildren(QLineEdit) if e.accessibleName().startswith('Address of the ')}
        for model in needed:
            edit = edits[f'Address of the {model}']
            edit.setText('GPIB0::7::INSTR')
            self.assertEqual(app.std_addr[model].get(), 'GPIB0::7::INSTR')
        timebase = next(w for w in app.shell.drawer_body.findChildren(type(app.section_mode_box)) if w.accessibleName() == 'Counter timebase')
        self.assertEqual(timebase.currentText(), app.counter_ref.get())
        timebase.setCurrentIndex(timebase.findText('INT'))
        self.assertEqual(app.counter_ref.get(), 'INT')

    def test_manual_calibration_window(self):
        app = self.app(fx.dmm_34461a_like(), manual_entry=True)
        self.assertIn('Manual Calibration', self.hn.root.windowTitle())
        self.assertNotIn('Performance Verification', self.hn.root.windowTitle())
        self.assertTrue(app.shell.title_label.text().endswith('  -  Manual Calibration'))
        self.assertTrue(app.shell.subtitle.get().startswith('Manual calibration: you set the stimulus'))
        self.assertFalse(app.cal_combo.isEnabled())
        self.assertFalse(app.btn_find.isEnabled())
        texts = [lab.text() for lab in app.shell.notice_holder.findChildren(QLabel)]
        self.assertFalse([t for t in texts if t.startswith('For each point the calibrator is programmed')])
        self.assertTrue([t for t in texts if t.startswith('Manual calibration "')])
        self.assertIsNotNone(app.grid_entry)

    def test_period_box_only_with_more_than_one_period(self):
        app = self.app(fx.dmm_34461a_like())
        periods = [p['id'] for p in app.dsb.get('periods', [])]
        found = [w for w in app.shell.drawer_body.findChildren(type(app.section_mode_box)) if w.accessibleName() == 'Specification period']
        self.assertEqual(bool(found), len(periods) > 1)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class TypedReadingWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp.create_app()

    def setUp(self):
        self.hn = Q.QtHarness(None).start()
        self.app = self.hn.make_app(spec_of(fx.dmm_34461a_like()), demo=True)
        self.p = next(p for p in self.app.points if p['test'] == 'numeric')

    def tearDown(self):
        self.hn.stop()

    def dialog(self, **kw):
        return OV.TypedDialog(self.hn.root, self.p, len(self.app.points), dsb_override.parse_typed, **kw)

    def test_a_refused_text_shows_the_reason_and_the_window_stays(self):
        dlg = self.dialog()

        def script(d):
            QTest.keyClicks(d.entry, '1,5')
            QTest.keyClick(d.entry, Qt.Key.Key_Return)
            self.assertTrue(d.isVisible())
            self.assertEqual(d.error.text(), 'Use a decimal point, not a comma.')
            d.entry.setText('')
            self.assertEqual(d.error.text(), '')
        run_dialog(dlg, script)
        self.assertIsNone(dlg.value)

    def test_the_confirmation_must_be_yes(self):
        text = f'{self.p["nominal"] / self.p["factor"]:.9g}'
        asked = []

        def answer(rec):
            if rec['title'] == 'Use this reading?':
                asked.append(rec['text'])
                return len(asked) > 1                                   # No the first time, Yes the second
            return None
        self.hn.answers.rules.append(answer)
        dlg = self.dialog()

        def script(d):
            d.entry.setText(text)
            Q.press(d, 'Use this reading  (Enter)')
            self.assertTrue(d.isVisible() and d.value is None)          # No: the window stays, the entry has the focus
            Q.press(d, 'Use this reading  (Enter)')
        run_dialog(dlg, script)
        self.assertEqual(len(asked), 2)
        self.assertEqual(dlg.value.value, self.p['nominal'])
        self.assertIn(f'point {self.p["n"]}', asked[0])
        self.assertEqual(self.hn.port.prompts[-1]['kind'], 'ask_yes_no')

    def test_cancel_text_reason_and_stored_reading(self):
        dlg = self.dialog(reason='the standard timed out', cancel_text='Stop run', stored='1.0002 V')
        self.assertIsNotNone(dlg.reason_label)
        self.assertIsNone(dlg.stored_label)                                # a failure reason replaces the stored-reading line
        run_dialog(dlg, lambda d: Q.press(d, 'Stop run'))
        self.assertIsNone(dlg.value)
        dlg = self.dialog(stored='1.0002 V', demo=True)
        self.assertEqual(dlg.stored_label.text(), 'Stored reading: 1.0002 V. Typing a value replaces it.')
        self.assertIn('DEMO', dlg.demo_label.text())
        run_dialog(dlg, lambda d: QTest.keyClick(d, Qt.Key.Key_Escape))
        self.assertIsNone(dlg.value)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class PreRunList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp.create_app()

    def test_cancel_is_the_default_and_accept_must_be_pressed(self):
        text = dsb_prerun.list_text(dict(lines=[f'cmd {i}' for i in range(70)]))
        self.assertTrue(text.endswith('... and 10 more'))
        dlg = PV.PreRunDialog(None, 'intro text', text)
        self.assertEqual(dlg.windowTitle().replace(' [DEMO]', ''), 'Unverified commands: accept before a real run')
        self.assertTrue(dlg.cancel_button.isDefault())
        self.assertFalse(dlg.accept_button.isDefault())
        run_dialog(dlg, lambda d: QTest.keyClick(d, Qt.Key.Key_Return))        # Enter = Cancel
        self.assertFalse(dlg.go)
        dlg = PV.PreRunDialog(None, 'intro text', text)
        run_dialog(dlg, lambda d: Q.press(d, 'Accept and run'))
        self.assertTrue(dlg.go)
        dlg = PV.PreRunDialog(None, 'intro text', text)
        run_dialog(dlg, lambda d: QTest.keyClick(d, Qt.Key.Key_Escape))
        self.assertFalse(dlg.go)
        self.assertEqual(dlg.text.toPlainText(), text)
        self.assertTrue(dlg.text.isReadOnly())


if __name__ == '__main__':
    unittest.main()
