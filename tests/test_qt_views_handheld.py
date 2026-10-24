"""Qt twins of the handheld meter windows (QT-H): handheld_dmm_view_qt (main window, reading / IR-problem / dial windows) and iflex_option_view_qt, reached through QtUiPort.

Headless (QT_QPA_PLATFORM=offscreen), skipped when PySide6 is not importable.

  * Windows: ReadingDialog / IrProblemDialog / RangeDialog driven with QTest (Enter, Esc, validation, annunciator, Fill, yes/no).
  * Golden prompts: all 3 scenarios of tests/golden_ui/ui_prompts_handheld.json and all 15 of ui_prompts_handheld_families.json run through QtUiPort and the REAL Qt
    windows with a scripted operator (tests/qt_handheld_harness.py): the same kinds, titles, texts, buttons, answers and order as the Tk build recorded.
  * Engine level: the 117, 289, 376 + iFlex, MM325 and a two-meter run queue give the same rows, statuses and detail text through the Qt window as through the Tk-level
    harness; the run buttons are enabled / disabled the same way while busy and idle as the Tk window does it.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

try:
    import tkinter  # noqa: F401
    for _sub in ('messagebox', 'filedialog', 'simpledialog'):          # tests/dsb_run_harness.py (imported by ui_prompt_capture) expects them in sys.modules
        try:
            __import__('tkinter.' + _sub)
        except ImportError:
            pass
except ImportError:                                  # the CI sandbox has none
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
    from PySide6.QtWidgets import QApplication, QCheckBox, QMainWindow, QPushButton, QRadioButton

    import handheld_engine_cases as E
    import qt_handheld_harness as Q
    import ui_prompt_capture as C
    import ui_port
    import handheld_dmm as hh
    import handheld_dmm_view_qt as V
    import iflex_option
    from qtui import app as qapp
    from ui_port import Answers


def canon(obj):
    return json.loads(json.dumps(obj))


def a_point(**kw):
    p = dict(id='1', n=1, section='DC volts', test='numeric', switch='V DC', range='600.0 V', group='DCV', applied=True, note='', display_unit='V', tol_text='',
             low='0.9', high='1.1', nominal=1.0, factor=1.0, base_unit='V', dial=None)
    p.update(kw)
    return p


def run_dialog(dlg, script, wait_ms=60):
    """Show `dlg` modally and run `script(dlg)` from inside its event loop (a dialog still open afterwards is rejected, so a failing script cannot hang the run)."""
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
class Windows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp.create_app()

    def reading(self, mode='numeric', **kw):
        args = dict(parent=None, p=a_point(), total=10, out_text='1.0000 V', out_note='Output is ON', accept='0.9 to 1.1 V', mode=mode, question='Is it lit?', unit='V')
        args.update(kw)
        return V.ReadingDialog(args.pop('parent'), args.pop('p'), args.pop('total'), args.pop('out_text'), args.pop('out_note'), args.pop('accept'), args.pop('mode'), **args)

    def test_numeric_enter_records_the_typed_text(self):
        dlg = self.reading()
        run_dialog(dlg, lambda d: (QTest.keyClicks(d.entry, '1.0003'), QTest.keyClick(d.entry, Qt.Key.Key_Return)))
        self.assertEqual(dlg.answer['action'], 'record')
        self.assertEqual(dlg.answer['text'], '1.0003')
        self.assertTrue(dlg.windowTitle().startswith('Point 1 of 10'))

    def test_a_refused_entry_stays_open_with_the_reason_and_esc_is_stop(self):
        def bad(text):
            raise ValueError('Enter the number as the meter shows it.')
        dlg = self.reading(validate=bad)

        def script(d):
            QTest.keyClicks(d.entry, 'abc')
            QTest.keyClick(d.entry, Qt.Key.Key_Return)
            self.assertTrue(d.isVisible())
            self.assertEqual(d.error.text(), 'Enter the number as the meter shows it.')
            QTest.keyClick(d, Qt.Key.Key_Escape)
        run_dialog(dlg, script)
        self.assertEqual(dlg.answer['action'], 'stop')

    def test_skip_and_stop_buttons(self):
        for name, action in (('Skip point', 'skip'), ('Stop run', 'stop')):
            dlg = self.reading()
            run_dialog(dlg, lambda d, _n=name: Q.press(d, _n))
            self.assertEqual(dlg.answer['action'], action)

    def test_yes_no_needs_a_choice(self):
        dlg = self.reading('yesno')

        def script(d):
            Q.press(d, 'Record  (Enter)')
            self.assertTrue(d.isVisible())
            self.assertEqual(d.error.text(), 'Choose Yes or No.')
            next(r for r in d.findChildren(QRadioButton) if r.text().startswith('No')).click()
            Q.press(d, 'Record  (Enter)')
        run_dialog(dlg, script)
        self.assertEqual((dlg.answer['action'], dlg.answer['yes']), ('record', False))

    def test_the_annunciator_box_only_when_asked_and_its_state_comes_back(self):
        dlg = self.reading(annunciator=True)

        def script(d):
            box = next(c for c in d.findChildren(QCheckBox) if c.text() == 'The AC annunciator is ON')
            box.setChecked(True)
            QTest.keyClicks(d.entry, '1')
            Q.press(d, 'Record  (Enter)')
        run_dialog(dlg, script)
        self.assertTrue(dlg.answer['ann'])
        self.assertFalse([c for c in self.reading().findChildren(QCheckBox)])

    def test_the_fill_button_only_in_demo_and_types_the_value(self):
        self.assertNotIn(hh.virtualbench.FILL_TEXT, [b.text() for b in self.reading().findChildren(QPushButton)])
        dlg = self.reading(demo_fill=lambda: '1.0001')

        def script(d):
            Q.press(d, hh.virtualbench.FILL_TEXT)
            self.assertEqual(d.entry.text(), '1.0001')
            Q.press(d, 'Record  (Enter)')
        run_dialog(dlg, script)
        self.assertEqual(dlg.answer['text'], '1.0001')

    def test_the_countdown_calls_on_expire_once(self):
        hits = []
        dlg = self.reading(limit_s=0.05, on_expire=lambda: hits.append(1))
        run_dialog(dlg, lambda d: (QTest.qWait(700), Q.press(d, 'Stop run')), wait_ms=10)
        self.assertEqual(hits, [1])

    def test_ir_problem_answers(self):
        for press_, want in (('Re-check  (Enter)', 'retry'), ('Type the reading instead', 'type'), ('Skip point', 'skip'), ('Stop run', 'stop')):
            dlg = V.IrProblemDialog(None, a_point(), 5, ['The meter is in the wrong function'], 'V DC, auto range')
            run_dialog(dlg, lambda d, _p=press_: Q.press(d, _p))
            self.assertEqual(dlg.answer, want)
        dlg = V.IrProblemDialog(None, a_point(), 5, ['x'], '')
        run_dialog(dlg, lambda d: QTest.keyClick(d, Qt.Key.Key_Return))
        self.assertEqual(dlg.answer, 'retry')
        dlg = V.IrProblemDialog(None, a_point(), 5, ['x'], '')
        run_dialog(dlg, lambda d: QTest.keyClick(d, Qt.Key.Key_Escape))
        self.assertEqual(dlg.answer, 'stop')

    def test_range_dialog_with_the_mm325_dial(self):
        spec = hh.load_spec('klein_mm325_pv.json')
        dial = spec['dial']
        pos = next(iter(dial['positions']))
        point = a_point(dial=pos, dial_text='DC V', switch='V DC', range='4.000 V', note='Auto range')
        for press_, want in (('Range selected - continue  (Enter)', 'ok'), ('Skip point', 'skip'), ('Stop run', 'stop')):
            dlg = V.RangeDialog(None, point, 3, dial, 'The calibrator is in STANDBY.')
            self.assertIsNotNone(dlg.picture)
            run_dialog(dlg, lambda d, _p=press_: Q.press(d, _p))
            self.assertEqual(dlg.answer, want)
        dlg = V.RangeDialog(None, point, 3, dial, 'x')
        run_dialog(dlg, lambda d: QTest.keyClick(d, Qt.Key.Key_Escape))
        self.assertEqual(dlg.answer, 'stop')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class GoldenPrompts(unittest.TestCase):
    """The prompts of the Tk build (fixtures recorded from the unported engines) through QtUiPort and the real Qt windows."""

    def check(self, runner, fixture):
        want = json.loads((GOLDEN / fixture).read_text(encoding='utf-8'))
        got = canon(runner(lambda answers=None: Q.QtHarness(answers)))
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], f'{fixture}: scenario {scenario}')

    def test_handheld_3_scenarios(self):
        self.check(C._run_handheld, 'ui_prompts_handheld.json')

    def test_handheld_families_15_scenarios(self):
        self.check(C._run_handheld_families, 'ui_prompts_handheld_families.json')


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# engine level: the same rows, statuses and detail text through the Qt window as through the Tk-level harness (tests/handheld_engine_cases.py)
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def tk_reference(name):
    """The Tk build's snapshot of the case, from a child process on the stubbed tkinter (the Tk-level harness needs no display, the real tkinter does)."""
    out = subprocess.run([sys.executable, str(ROOT / 'tests' / 'handheld_engine_cases.py'), name], capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    if out.returncode != 0:
        raise AssertionError(f'the Tk-level run of {name} failed:\n{out.stderr[-3000:]}')
    return json.loads(out.stdout)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class EngineLevel(unittest.TestCase):
    def check(self, name):
        tk = tk_reference(name)
        qt = canon(E.run_case(lambda answers: Q.QtHarness(answers), name))
        self.assertEqual(sorted(qt), sorted(tk))
        for key in tk:
            self.assertEqual(qt[key], tk[key], f'{name}: {key}')
        self.assertTrue(tk['found'] or tk['left'], 'the run recorded nothing')

    def test_117(self):
        self.check('117')

    def test_289(self):
        self.check('289')

    def test_376_with_the_iflex_option_off(self):
        self.check('376_iflex_off')

    def test_mm325(self):
        self.check('mm325')

    def test_two_meter_queue(self):
        self.check('queue_117')


class _Rec:
    """A widget stand-in that keeps the state the Tk view's sync_buttons gave it."""

    def __init__(self):
        self.state = None

    def configure(self, **kw):
        self.state = kw.get('state', self.state)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class WindowState(unittest.TestCase):
    NAMES = ('btn_run', 'btn_section', 'btn_rerun', 'btn_test', 'btn_load', 'btn_find', 'btn_stop')

    def tk_states(self, busy, n_modes):
        import handheld_dmm_view_tk as T
        fake = type('A', (), {})()
        for name in self.NAMES:
            setattr(fake, name, _Rec())
        fake.mode_buttons = [_Rec() for _ in range(n_modes)]
        T.sync_buttons(fake, busy)
        return {n: getattr(fake, n).state == 'normal' for n in self.NAMES}, [m.state == 'normal' for m in fake.mode_buttons]

    def test_buttons_are_enabled_and_disabled_like_tk_busy_and_idle(self):
        hn = Q.QtHarness(None)
        hn.start()
        try:
            app = hh.App(hn.root, '117', demo=True, spec=hh.load_spec('fluke_110_series_pv.json'), fast_demo=False)
            for busy in (False, True, False):
                app.busy = busy
                want_named, want_modes = self.tk_states(busy, len(app.mode_buttons))
                got_named = {n: getattr(app, n).isEnabled() for n in self.NAMES}
                self.assertEqual(got_named, want_named, f'busy={busy}')
                self.assertEqual([b.isEnabled() for b in app.mode_buttons], want_modes, f'busy={busy}')
        finally:
            hn.stop()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class MainWindow(unittest.TestCase):
    def setUp(self):
        self.hn = Q.QtHarness(None).start()

    def tearDown(self):
        self.hn.stop()

    def app(self, model='117', spec='fluke_110_series_pv.json', engine=hh, **kw):
        a = engine.App(self.hn.root, model, demo=True, spec=hh.load_spec(spec), fast_demo=False, **kw)
        self.hn.app = a
        return a

    def test_the_table_lists_every_point_and_selecting_a_row_fills_the_detail_line(self):
        app = self.app()
        self.assertEqual(app.tree.model().rowCount(), len(app.points))
        self.assertEqual(sorted(app.tree.get_children()), sorted(p['id'] for p in app.points))
        p = app.points[2]
        app.tree.selection_set(p['id'])
        QApplication.processEvents()
        self.assertTrue(app.detail.get().startswith(hh.describe(p)))
        self.assertIn('Accept:', app.detail.get())

    def test_title_buttons_and_the_demo_chip(self):
        app = self.app()
        self.assertEqual(self.hn.root.windowTitle(), f'{app.info["name"]} | Performance Verification [DEMO]')
        texts = {b.text() for b in self.hn.root.findChildren(QPushButton)}
        for want in ('▶  Run All Pending', 'Run Shown Section', 'Rerun Selected', 'Export Report (PDF)', 'Load progress', 'Save progress', 'Find instruments', 'Test connection'):
            self.assertIn(want, texts)
        self.assertEqual(app.shell.title_label.text(), f'{app.info["name"]}  -  Performance Verification')

    def test_the_iflex_bar_and_the_confirmation(self):
        app = self.app('376', 'fluke_376_pv.json', engine=iflex_option)
        self.assertIn('iflex', app._include_vars)
        box = next(c for c in app.include_bar.findChildren(QCheckBox))
        self.assertTrue(box.isChecked())
        n_before = len(app.points)
        self.hn.answers.rules.append(lambda r: False if r.get('title') == 'Skip the iFlex tests' else None)
        box.click()                                                     # the operator says No: nothing changes, the box goes back
        self.assertTrue(box.isChecked())
        self.assertEqual(len(app.points), n_before)
        self.hn.answers.rules.clear()
        box.click()                                                     # Yes: the iFlex points leave the run
        self.assertFalse(box.isChecked())
        self.assertLess(len(app.points), n_before)
        self.assertEqual(app._include_labels['iflex'].text(), app.include_text('iflex', short=True))

    def test_the_queue_rows_follow_the_meters(self):
        app = self.app('376', 'fluke_376_pv.json', engine=iflex_option)
        app.apply_queue([('4412', 'S-4412', 'T 1'), ('4413', 'S-4413', 'T 2')], 'point_by_point')
        QApplication.processEvents()
        self.assertEqual(sorted(app._inc_row_vars), ['4412', '4413'])
        self.assertTrue(app.queue_pill.isVisible() or app.queue_pill.winfo_manager() == 'pack')


if __name__ == '__main__':
    unittest.main()
