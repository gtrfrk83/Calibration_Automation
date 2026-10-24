"""Qt twins of the three guided Adjustment windows (QT-G1b): keithley2000_adjust_view_qt, fluke8808a_adjust_view_qt, fluke8846a_adjust_view_qt.

Headless (QT_QPA_PLATFORM=offscreen), skipped when PySide6 is not importable.  The REAL launchers (Procedures/Keithley_2000_Adjustment.py, Fluke_8808A_Adjustment.py,
Fluke_8846A_Adjustment.py) are built on a real QMainWindow with the Qt view, in demo mode (virtual instruments) or, for the 8846A, over the fake serial meter of
tests/ui_prompt_capture.py, and driven through the SAME sequences as the recorded Tk scenarios.  The prompts the port saw must equal tests/golden_ui/
ui_prompts_adjustments.json and ui_prompts_adj8846a.json.  The guards of the adjustments (calibration code / password masked and never logged, relock, the SAVE / COMMIT
confirmation, the committed flag, the As Left reminders, the reset confirmation, button states by session state) are asserted on the Qt windows."""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'Procedures'))

import _tk_stub  # noqa: E402

# the launchers' toolkit-free helpers still import ui_theme (tkinter): always run over the stub, like every other launcher test, even where a real tkinter exists
if not getattr(sys.modules.get('tkinter'), '_cal_stub', False):
    for _k in [k for k in sys.modules if k == 'tkinter' or k.startswith('tkinter.') or k == '_tkinter']:
        del sys.modules[_k]
    sys.modules['tkinter'] = None                    # makes `import tkinter` fail, so install() puts the stub modules in
    _tk_stub.install()

try:
    import PySide6.QtWidgets  # noqa: F401
    HAVE_QT = True
except ImportError:
    HAVE_QT = False

if HAVE_QT:
    from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton
    import ui_port
    from qtui import app as qapp
    from qtui import shell_helpers
    from qtui.vars import QtVar
    from tests import ui_prompt_capture as C

    class QtScriptedPort(C._HarnessPort):
        """The scripted operator (records and answers every prompt, masks secrets) with the Qt window plumbing: view -> <name>_qt, QtVar variables, real event pumping."""

        def view(self, name):
            return importlib.import_module(f'{name}_qt')

        def var(self, value='', kind='str'):
            return QtVar(value, kind)

        def update(self, win):
            QApplication.processEvents()

        def flush(self, win):
            QApplication.processEvents()

        def close(self, win):
            win.setProperty('_calsuite_closing', True)
            win.close()

        def on_close(self, win, fn):
            import ui_port_qt
            ui_port_qt._CloseFilter(win, fn)                 # the real port's close handling: the close button calls the launcher's handler

    class QtHarness(C.PortHarness):
        def __init__(self, answers=None, home=None):
            super().__init__(answers, home)
            qapp.create_app()
            self.root = QMainWindow()
            self.roots = [self.root]

        def start(self):
            super().start()
            self.port = QtScriptedPort(self.answers, self)
            ui_port.set_ui(self.port)
            return self

        def pump(self, seconds=0):
            for _ in range(3):
                QApplication.processEvents()
            return True

        def stop(self):
            from PySide6.QtCore import QEvent
            for r in self.roots:
                try:
                    r.setProperty('_calsuite_closing', True)
                    r.close()
                    r.deleteLater()                       # a stale window must not stay the 'active window' a later test's dialogs are parented to
                except RuntimeError:                      # already deleted (stop() is also registered as a cleanup)
                    pass
            self.roots = []
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            super().stop()

    class _SelectableTable:
        """The scenario of the 8846A selects a step by `app.tree.sel = ('2',)` (the Tk-level fake table); on the real table that selects the row."""

        @staticmethod
        def sel_set(self, value):
            self.selection_set(*value)
            for _ in range(3):
                QApplication.processEvents()


def fixture(name):
    return json.loads((ROOT / 'tests' / 'golden_ui' / name).read_text(encoding='utf-8'))


def canon(obj):
    return json.loads(json.dumps(obj))


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class PromptSequences(unittest.TestCase):
    """The Qt windows drive the same prompts, in the same order, as the Tk build (the recorded fixtures)."""

    def test_keithley_and_8808a_launchers_reproduce_the_recorded_prompts(self):
        got = canon(C.SCENARIOS['adjustments'](QtHarness))
        want = fixture('ui_prompts_adjustments.json')
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], scenario)

    def test_8846a_launcher_reproduces_the_recorded_prompts(self):
        with mock.patch.object(shell_helpers.ResultsTree, 'sel', property(lambda self: self.selection(), _SelectableTable.sel_set), create=True):
            got = canon(C.SCENARIOS['adj8846a'](QtHarness))
        want = fixture('ui_prompts_adj8846a.json')
        self.assertEqual(sorted(got), sorted(want))
        for scenario in want:
            self.assertEqual(got[scenario], want[scenario], scenario)


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------------------------------------------------------
VIEWS = {'keithley': ('keithley2000_adjust_view', 'Keithley_2000_Adjustment'), 'f8808a': ('fluke8808a_adjust_view', 'Fluke_8808A_Adjustment'),
         'f8846a': ('fluke8846a_adjust_view', 'Fluke_8846A_Adjustment')}
# sync_buttons arguments -> the attribute of the window each one drives (the order of the Tk view's `en(...)` statements)
BUTTONS = {'keithley': ('btn_connect', 'btn_start', 'btn_unlock', 'btn_run', 'btn_save', 'btn_abort', 'btn_close'),
           'f8808a': ('btn_connect', 'btn_start', 'btn_enter', 'btn_run', 'btn_finish', 'btn_abort', 'btn_close'),
           'f8846a': ('btn_connect', 'btn_start', 'btn_resume', 'btn_review', 'btn_unlock', 'btn_exec', 'btn_commit', 'btn_relock')}


def window_text(root):
    """Every piece of text the window shows: labels, buttons, line edits, combo boxes, table cells (headers included)."""
    from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit
    out = []
    for w in root.findChildren(QLabel):
        out.append(w.text())
    for w in root.findChildren(QPushButton):
        out.append(w.text())
    for w in root.findChildren(QLineEdit):
        out.append(w.text())
    for w in root.findChildren(QComboBox):
        out.append(w.currentText())
    for t in root.findChildren(shell_helpers.ResultsTree):
        for r in t.rows():
            out.extend(str(v) for v in r.values)
    return '\n'.join(out)


def rows(table):
    return [list(r.values) for r in table.rows()]


class Mirror:
    """Wraps the Qt view's sync_buttons: after every sync each button must be enabled exactly when the launcher said so."""

    def __init__(self, tc, key, view_mod):
        self.tc, self.key, self.view, self.calls = tc, key, view_mod, []
        self.orig = view_mod.sync_buttons

    def __enter__(self):
        def wrapper(app, *args):
            self.orig(app, *args)
            self.calls.append(args)
            for name, want in zip(BUTTONS[self.key], args):
                self.tc.assertEqual(getattr(app, name).isEnabled(), bool(want), f'{self.key}: {name} after sync_buttons{args}')
            if self.key != 'f8846a':
                self.tc.assertEqual(app.scope_combo.isEnabled(), not args[-1], f'{self.key}: scope_combo')
        self.p = mock.patch.object(self.view, 'sync_buttons', wrapper)
        self.p.start()
        return self

    def __exit__(self, *a):
        self.p.stop()


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class QtBase(unittest.TestCase):
    def setUp(self):
        self.hn = QtHarness(None)
        self.hn.start()
        self.addCleanup(self.hn.stop)
        self.tmp = Path(tempfile.mkdtemp())

    def launcher(self, key):
        return importlib.import_module(VIEWS[key][1])

    def view(self, key):
        return importlib.import_module(VIEWS[key][0] + '_qt')

    def tk_view(self, key):
        return importlib.import_module(VIEWS[key][0] + '_tk')

    def new_app(self, key, demo=True):
        mod = self.launcher(key)
        if key == 'f8846a':
            for name in ('_registry_path', '_legacy_path'):
                p = mock.patch.object(mod, name, lambda _n=name: self.tmp / f'{_n}.sqlite3')
                p.start()
                self.addCleanup(p.stop)
        self.hn.root = QMainWindow()                          # one window per launcher
        self.hn.roots.append(self.hn.root)
        app = mod.App(self.hn.root, demo=demo)
        self.hn.app = app
        return app

    def pump(self):
        from PySide6.QtCore import QEvent
        for _ in range(4):
            QApplication.processEvents()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Structure(QtBase):
    """The windows are the Qt twins: same functions as the Tk views, same texts, same initial state."""

    def test_the_qt_views_have_the_public_functions_of_the_tk_views(self):
        import inspect
        for key in VIEWS:
            tk, qt = self.tk_view(key), self.view(key)
            for name, fn in inspect.getmembers(tk, inspect.isfunction):
                if name.startswith('_') or fn.__module__ != tk.__name__:
                    continue
                self.assertTrue(hasattr(qt, name), f'{key}: {name}')
                self.assertEqual(list(inspect.signature(getattr(qt, name)).parameters), list(inspect.signature(fn).parameters), f'{key}: {name}')

    def test_the_port_resolves_the_launchers_to_the_qt_view(self):
        for key in VIEWS:
            app = self.new_app(key)
            self.assertEqual(app.ui_view.__name__, VIEWS[key][0] + '_qt')

    def test_no_toolkit_import_in_the_qt_views(self):
        import ast
        for f in ('keithley2000_adjust_view_qt.py', 'fluke8808a_adjust_view_qt.py', 'fluke8846a_adjust_view_qt.py', 'qtui/adjust_window.py'):
            tree = ast.parse((ROOT / f).read_text(encoding='utf-8'))
            for n in ast.walk(tree):
                names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ''] if isinstance(n, ast.ImportFrom) else []
                for m in names:
                    self.assertNotIn(m.split('.')[0], ('tkinter', 'ui_theme', 'ui_shell', 'ui_port_tk'), f'{f}: {m}')
                    self.assertFalse(m.endswith('_view_tk'), f'{f}: {m}')

    def test_titles_pills_buttons_and_notice_of_each_window(self):
        want = {'keithley': ('Keithley 2000 | Guided Adjustment [DEMO]', ['DEMO MODE  -  virtual instruments, nothing saved', '2000: not connected', 'No adjustment record', 'Calibration LOCKED'],
                             ['Connect', 'Start adjustment record', 'Unlock calibration', 'Run next step', 'Dates and SAVE', 'Abort and lock', 'Lock and disconnect']),
                'f8808a': (None, ['DEMO MODE  -  virtual instruments, nothing saved', '8808A: not connected', 'No adjustment record', 'Calibration mode: closed'],
                           ['Connect', 'Start adjustment record', 'Calibration mode entered', 'Run next point', 'Finish (EXIT)', 'Abort', 'Disconnect']),
                'f8846a': ('Fluke 8846A | Guided Adjustment v57 [DEMO]', ['DEMO MODE  -  commands simulated', 'Meter: DEMO (simulated)', 'No adjustment record', 'Calibration LOCKED'],
                           ['Connect / verify 8846A', 'Start new adjustment record', 'Resume existing record', 'Mark setup reviewed', 'Unlock adjustment (authorised)',
                            'Execute selected verified open step', 'Commit coefficients (CAL:REC)', 'Relock and disconnect'])}
        for key, (title, pills, buttons) in want.items():
            app = self.new_app(key)
            root = self.hn.root
            if title:
                self.assertEqual(root.windowTitle(), title)
            else:
                self.assertTrue(root.windowTitle().endswith(' [DEMO]'))
            shown = [b.text() for b in root.findChildren(shell_helpers.Pill)]
            self.assertEqual(shown, pills, key)
            texts = [b.text() for b in root.findChildren(QPushButton)]
            for b in buttons:
                self.assertIn(b, texts, key)
            names = BUTTONS[key]
            self.assertEqual([getattr(app, n).text() for n in names], [b for b in buttons if b != 'Refresh ports'] if key != 'f8846a' else
                             [buttons[0], buttons[1], buttons[2], buttons[3], buttons[4], buttons[5], buttons[6], buttons[7]], key)
            E = importlib.import_module(self.launcher(key).__name__)
            if key != 'f8846a':
                self.assertIn(E.NOTICE, window_text(root))
                self.assertIn('This changes the instrument calibration', window_text(root))
            self.assertIn('NEXT', window_text(root))

    def test_the_steps_are_listed_in_the_order_of_the_procedure_and_the_header_does_not_sort(self):
        app = self.new_app('f8846a')
        E = self.launcher('f8846a')
        self.assertEqual([r[2] for r in rows(app.tree)], [s[1] for s in E.STEPS])
        self.assertEqual([r[0] for r in rows(app.tree)], list(range(1, len(E.STEPS) + 1)))
        self.assertEqual([r[4] for r in rows(app.tree)], ['Open-step eligible' if s[5] else 'Guided review' for s in E.STEPS])
        for key in ('keithley', 'f8808a'):
            a = self.new_app(key)
            before = rows(a.tree)
            a.tree.sort_by(a.tree.source_model.columns[1].key)         # a (programmatic) sort must not be offered by the header
            self.assertFalse(a.tree.horizontalHeader().sectionsClickable())
            self.assertTrue(before)

    def test_the_8846a_audit_log_is_hidden_until_ticked_and_the_others_show_it(self):
        a = self.new_app('f8846a')
        self.assertTrue(a.log_box.isHidden())
        self.assertFalse(a.show_log.get())
        a.show_log.set(True)
        a._toggle_log()
        self.assertFalse(a.log_box.isHidden())
        for key in ('keithley', 'f8808a'):
            a = self.new_app(key)
            self.assertFalse(a.log_box.isHidden())
            a.show_log.set(False)
            a._toggle_log()
            self.assertTrue(a.log_box.isHidden())


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class TkParity(QtBase):
    """The pill texts / kinds and the button states of the Qt view equal the Tk view's for every input (the Tk view run over fake widgets)."""

    class FakeBtn:
        def __init__(self):
            self.state = None

        def configure(self, **kw):
            self.state = kw.get('state', self.state)

    class FakePill:
        def __init__(self):
            self.v = None

        def set(self, text, kind=None):
            self.v = (text, kind)

    def test_sync_pills(self):
        import itertools
        for key in VIEWS:
            tk, qt = self.tk_view(key), self.view(key)
            names = [n for n in ('pill_meter', 'pill_run', 'pill_lock', 'pill_cal') if n in ('pill_meter', 'pill_run') or (n == 'pill_cal') == (key == 'f8808a')]
            for live, flag, demo, rid in itertools.product((False, True), (False, True), (False, True), (None, 7)):
                ref = SimpleNamespace(demo=demo, run_id=rid, audit=SimpleNamespace(run_id=rid), **{n: self.FakePill() for n in names})
                tk.sync_pills(ref, live, flag)
                mine = SimpleNamespace(demo=demo, run_id=rid, audit=SimpleNamespace(run_id=rid), **{n: shell_helpers.Pill(None, '', 'neutral') for n in names})
                qt.sync_pills(mine, live, flag)
                for n in names:
                    self.assertEqual((getattr(mine, n).text(), getattr(mine, n).kind()), getattr(ref, n).v, f'{key} {n} live={live} flag={flag} demo={demo} rid={rid}')

    def test_sync_buttons(self):
        import itertools
        for key in VIEWS:
            tk, qt = self.tk_view(key), self.view(key)
            n = len(BUTTONS[key]) + (0 if key == 'f8846a' else 1)
            names = BUTTONS[key]
            for args in itertools.product((False, True), repeat=n):
                ref = SimpleNamespace(**{b: self.FakeBtn() for b in names}, scope_combo=self.FakeBtn())
                tk.sync_buttons(ref, *args)
                mine = SimpleNamespace(**{b: shell_helpers.button(None, b) for b in names}, scope_combo=shell_helpers.combobox(None, None, ['a']))
                qt.sync_buttons(mine, *args)
                for b in names:
                    self.assertEqual(getattr(mine, b).isEnabled(), getattr(ref, b).state == 'normal', f'{key} {b} {args}')
                if key != 'f8846a':
                    self.assertEqual(mine.scope_combo.isEnabled(), ref.scope_combo.state == 'readonly', f'{key} scope {args}')


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# the guided flows, through the Qt windows
# ----------------------------------------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class Keithley(QtBase):
    def setUp(self):
        super().setUp()
        from drivers.simulated_k2000_cal import SIM_CODE
        self.code = SIM_CODE
        self.hn.answers.rules.append(lambda r: SIM_CODE if r['kind'] == 'ask_text' and r['title'] == 'Calibration code' else None)

    def prompts(self):
        return self.hn.port.prompts

    def test_state_machine_of_the_buttons_through_a_whole_demo_adjustment(self):
        view = self.view('keithley')
        with Mirror(self, 'keithley', view) as m:
            app = self.new_app('keithley')
            en = lambda: {n: getattr(app, n).isEnabled() for n in BUTTONS['keithley']}
            self.assertEqual(en(), dict(btn_connect=True, btn_start=False, btn_unlock=False, btn_run=False, btn_save=False, btn_abort=False, btn_close=False))
            app.asset.set('A-1'); app.serial.set('S-1'); app.tech.set('T')
            app.connect()
            self.assertEqual(en(), dict(btn_connect=False, btn_start=True, btn_unlock=False, btn_run=False, btn_save=False, btn_abort=False, btn_close=True))
            app.start_record()
            self.assertEqual(en(), dict(btn_connect=False, btn_start=False, btn_unlock=True, btn_run=False, btn_save=False, btn_abort=False, btn_close=True))
            self.assertFalse(app.scope_combo.isEnabled())                       # the scope cannot change once a record is active
            self.assertEqual(app.pill_lock.text(), 'Calibration LOCKED')
            self.assertEqual(app.pill_lock.kind(), 'good')
            app.unlock()
            self.assertEqual(app.pill_lock.text(), 'Calibration UNLOCKED')
            self.assertEqual(app.pill_lock.kind(), 'bad')
            self.assertEqual(en(), dict(btn_connect=False, btn_start=False, btn_unlock=False, btn_run=True, btn_save=False, btn_abort=True, btn_close=True))     # abort: unlocked
            n = 0
            while app.session.next_step() and n < 4:
                app.run_next()
                n += 1
            self.assertTrue(app.btn_abort.isEnabled())                          # attempts were made: Abort and lock is offered
            states = [r[5] for r in rows(app.tree)]
            self.assertEqual(states.count('done'), n)
            self.assertTrue(m.calls)
            # the audit table shows the newest row first
            log = rows(app.log_table)
            self.assertTrue(log)
            times = [r[0] for r in log]
            self.assertEqual(times, sorted(times, reverse=True))
            app.abort(ask=False)
            self.assertEqual(app.pill_lock.text(), 'Calibration LOCKED')
            self.assertFalse(app.btn_run.isEnabled())

    def test_the_calibration_code_is_never_shown_or_logged_by_the_window(self):
        app = self.new_app('keithley')
        app.asset.set('A-1'); app.serial.set('S-1'); app.tech.set('T')
        app.connect(); app.start_record(); app.unlock()
        unlock_prompt = [p for p in self.prompts() if p['kind'] == 'ask_text' and p['title'] == 'Calibration code'][0]
        self.assertEqual(unlock_prompt['answer'], '<masked>')
        self.assertTrue(unlock_prompt.get('masked'))
        for _ in range(2):
            app.run_next()
        shown = window_text(self.hn.root) + '\n'.join(app.log_table.get_children())
        self.assertNotIn(self.code, shown.replace(unlock_prompt['text'], ''))
        self.assertNotIn(self.code, repr([r for r in rows(app.log_table)]))

    def test_closing_the_window_while_unlocked_asks_first(self):
        app = self.new_app('keithley')
        app.asset.set('A-1'); app.serial.set('S-1'); app.tech.set('T')
        app.connect(); app.start_record(); app.unlock()
        n = len(self.prompts())
        self.hn.root.show()
        self.hn.root.close()                                  # the close button: the launcher's on_close decides
        self.pump()
        new = self.prompts()[n:]
        self.assertTrue(new and new[0]['title'] == 'Lock first' or any(p['title'] == 'Lock first' for p in new), new)
        self.assertTrue(self.hn.root.isVisible())             # not closed: the calibration is still UNLOCKED
        self.assertEqual(app.pill_lock.text(), 'Calibration UNLOCKED')


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class F8808A(QtBase):
    def test_state_machine_of_the_buttons_and_the_pills(self):
        view = self.view('f8808a')
        with Mirror(self, 'f8808a', view):
            app = self.new_app('f8808a')
            en = lambda: {n: getattr(app, n).isEnabled() for n in BUTTONS['f8808a']}
            self.assertEqual(en(), dict(btn_connect=True, btn_start=False, btn_enter=False, btn_run=False, btn_finish=False, btn_abort=False, btn_close=False))
            app.asset.set('A-1'); app.serial.set('S-1'); app.tech.set('T')
            app.connect()
            app.start_record()
            self.assertFalse(app.scope_combo.isEnabled())
            self.assertEqual(app.pill_cal.text(), 'Calibration mode: closed')
            app.enter_calibration()
            self.assertEqual(app.pill_cal.text(), 'Calibration mode: OPEN')
            self.assertEqual(app.pill_cal.kind(), 'bad')
            self.assertTrue(app.btn_run.isEnabled())
            for _ in range(3):
                if app.session.next_step():
                    app.run_next()
            self.assertEqual([r[4] for r in rows(app.tree)].count('done'), 3)
            app.abort(ask=False)
            self.assertEqual(app.pill_cal.text(), 'Calibration mode: closed')
            self.assertFalse(app.btn_run.isEnabled())

    def test_the_ter_option_is_off_by_default_and_follows_the_tick_box(self):
        from PySide6.QtWidgets import QCheckBox
        app = self.new_app('f8808a')
        box = [c for c in self.hn.root.findChildren(QCheckBox) if c.text().startswith('Also send *TER once (UNVERIFIED')][0]
        self.assertFalse(box.isChecked())
        self.assertFalse(app.use_ter.get())
        box.click()
        self.assertTrue(app.use_ter.get())


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class F8846A(QtBase):
    def fake_app(self):
        """The launcher on the fake serial meter (as tests/ui_prompt_capture._run_adj8846a), real table selection."""
        mod = self.launcher('f8846a')
        meter = C._FakeMeter8846A()
        p = mock.patch.object(mod, 'open_meter', return_value=meter)
        p.start()
        self.addCleanup(p.stop)
        app = self.new_app('f8846a', demo=False)
        app.asset.set('A-8846'); app.serial.set('S-1'); app.tech.set('T')
        return app, meter

    def select(self, app, i):
        app.tree.selection_set(str(i))
        self.pump()

    def en(self, app):
        return {n: getattr(app, n).isEnabled() for n in BUTTONS['f8846a']}

    def test_button_states_follow_the_session_and_the_selected_step(self):
        self.hn.answers.rules.append(lambda r: 'Pw12' if r['kind'] == 'ask_text' and r['title'] in ('Calibration password', 'Relock calibration') else None)
        self.hn.answers.rules.append(lambda r: 'COMMIT 8846A' if r['kind'] == 'ask_text' and r['title'] == 'Final confirmation' else None)
        with Mirror(self, 'f8846a', self.view('f8846a')):
            app, meter = self.fake_app()
            self.assertEqual(self.en(app), dict(btn_connect=True, btn_start=False, btn_resume=True, btn_review=False, btn_unlock=False, btn_exec=False, btn_commit=False,
                                                btn_relock=False))
            app.connect()
            self.assertEqual(app.pill_meter.text(), 'Meter: connected')
            app.start()
            self.assertEqual(app.pill_run.text(), f'Record #{app.run_id}')
            self.assertTrue(app.btn_review.isEnabled() and app.btn_unlock.isEnabled() and not app.btn_exec.isEnabled() and not app.btn_commit.isEnabled())
            self.select(app, 2)                                              # an eligible step (100 M open)
            self.assertIn('This step can be executed after you unlock adjustment.', app.detail.get())
            app.mark_reviewed()
            self.assertEqual(rows(app.tree)[2][4], 'Reviewed')
            app.unlock()
            self.assertEqual(app.pill_lock.text(), 'Calibration UNLOCKED')
            self.assertEqual(app.pill_lock.kind(), 'bad')
            self.assertTrue(app.btn_exec.isEnabled())                        # eligible step selected and unlocked
            self.select(app, 5)                                              # a review-only step: Execute is not offered
            self.assertFalse(app.btn_exec.isEnabled())
            self.assertIn('Guided review only', app.detail.get())
            self.select(app, 2)
            self.assertTrue(app.btn_exec.isEnabled())
            self.assertFalse(app.committed)
            app.execute()
            self.assertEqual(rows(app.tree)[2][4], 'Adjusted')
            self.assertIn(('adjust',), [c[:1] for c in meter.calls if isinstance(c, tuple)])
            app.commit()
            self.assertTrue(app.committed)
            self.assertIn('Run the independent As Left verification', app.next_hint.get())
            self.assertIn('record', meter.calls)
            reminder = [p for p in self.hn.port.prompts if p['title'] == 'As Left verification required']
            self.assertEqual(len(reminder), 1)
            self.assertIn('Perform independent As Left verification', reminder[0]['text'])
            app.disconnect()
            self.assertFalse(app.unlocked)
            self.assertFalse(app.committed)
            self.assertEqual(app.pill_lock.text(), 'Calibration LOCKED')
            self.assertIn('lock', meter.calls)

    def test_the_audit_log_lists_the_actions_newest_first_with_ok_and_error_marked(self):
        self.hn.answers.rules.append(lambda r: 'Pw12' if r['kind'] == 'ask_text' and r['title'] == 'Calibration password' else None)
        app, meter = self.fake_app()
        app.connect(); app.start()
        self.select(app, 0)
        app.mark_reviewed()
        app.unlock()
        log = rows(app.log_table)
        self.assertEqual([r[1] for r in log][:3], ['UNLOCK', 'SETUP_REVIEWED', 'RUN_STARTED'][:3])
        self.assertEqual(log[0][2], 'OK')
        t = app.log_table
        self.assertEqual(t.source_model.tone_of(t.rows()[0]), 'good')

    def test_closing_the_window_while_unlocked_relocks_first_and_a_wrong_password_keeps_it_unlocked(self):
        self.hn.answers.rules.append(lambda r: 'Pw12' if r['kind'] == 'ask_text' and r['title'] == 'Calibration password' else None)
        pws = iter(['bad pw!'])
        self.hn.answers.rules.append(lambda r: next(pws, None) if r['kind'] == 'ask_text' and r['title'] == 'Relock calibration' else None)
        app, meter = self.fake_app()
        app.connect(); app.start()
        app.unlock()
        self.assertTrue(app.unlocked)
        self.hn.root.show()
        n = len(self.hn.port.prompts)
        self.hn.root.close()
        self.pump()
        self.assertEqual([p['title'] for p in self.hn.port.prompts[n:]], ['Relock first'])
        self.assertTrue(self.hn.root.isVisible())
        app.disconnect()                                                    # a malformed password: the relock is NOT confirmed and the window says so
        last = self.hn.port.prompts[-1]
        self.assertEqual((last['kind'], last['title']), ('warning', 'Relock not confirmed'))
        self.assertTrue(app.unlocked)
        self.assertNotIn('lock', meter.calls)
        self.assertEqual(app.pill_lock.text(), 'Calibration UNLOCKED')

    def test_a_secret_is_never_in_any_text_of_the_window_or_the_audit_rows(self):
        self.hn.answers.rules.append(lambda r: 'Pw12' if r['kind'] == 'ask_text' and r['title'] in ('Calibration password', 'Relock calibration') else None)
        app, meter = self.fake_app()
        app.connect(); app.start(); app.unlock(); app.disconnect()
        self.assertTrue(app.log_table.rows())
        self.assertNotIn('Pw12', window_text(self.hn.root))
        for p in self.hn.port.prompts:
            if p['kind'] == 'ask_text' and p['title'] in ('Calibration password', 'Relock calibration'):
                self.assertEqual(p['answer'], '<masked>')
        import sqlite3
        con = sqlite3.connect(str(self.tmp / '_registry_path.sqlite3'))
        dump = repr(list(con.execute('select * from adjustment_events_8846a'))) + repr(list(con.execute('select * from adjustment_runs_8846a')))
        con.close()
        self.assertNotIn('Pw12', dump)

    def test_the_ports_picker_takes_the_ports_and_keeps_the_typed_name(self):
        app = self.new_app('f8846a')
        app.port.set('COM7')
        app.ui_view.set_ports(app, ['COM3', 'COM4'])
        self.assertEqual([app.port_combo.itemText(i) for i in range(app.port_combo.count())], ['COM3', 'COM4'])
        self.assertEqual(app.port.get(), 'COM7')                            # not replaced by the list: "you can still type a port name"


# ----------------------------------------------------------------------------------------------------------------------------------------------------
# real dialogs: the password entry of the 8846A through the Qt window and the REAL QtUiPort
# ----------------------------------------------------------------------------------------------------------------------------------------------------
def run_dialogs(call, handlers):
    """Run call(); every modal dialog (ModalDialog.run) that opens is handed to the next handler, which clicks it.  A dialog without a handler fails the test."""
    from PySide6.QtCore import QTimer
    from qtui.widgets import ModalDialog
    todo, errors, seen = list(handlers), [], []
    orig = ModalDialog.run

    def run(dlg):
        seen.append(dlg.windowTitle())
        if not todo:
            errors.append(f'unexpected dialog {dlg.windowTitle()!r}')
            QTimer.singleShot(0, dlg.reject)
        else:
            handler = todo.pop(0)

            def click():
                try:
                    handler(dlg)
                except BaseException as exc:              # noqa: BLE001 - close the dialog or the test hangs
                    errors.append(exc)
                    dlg.reject()
            QTimer.singleShot(0, click)
        return orig(dlg)
    with mock.patch.object(ModalDialog, 'run', run):
        out = call()
    for e in errors:
        raise e if isinstance(e, BaseException) else AssertionError(e)
    if todo:
        raise AssertionError(f'{len(todo)} expected dialogs never opened; saw {seen}')
    return out


@unittest.skipUnless(HAVE_QT, 'PySide6 is not installed')
class RealDialogs(QtBase):
    def setUp(self):
        super().setUp()
        import ui_port_qt
        from tests.test_ui_port_qt import press
        self.press = press
        self.hn.stop()                                        # no scripted port: the real one
        self.hn = QtHarness(None)
        self.hn.start()
        self.addCleanup(self.hn.stop)
        ui_port.set_ui(ui_port_qt.QtUiPort())
        self.addCleanup(lambda: ui_port.set_ui(None))
        mod = self.launcher('f8846a')
        self.meter = C._FakeMeter8846A()
        for name in ('_registry_path', '_legacy_path'):
            p = mock.patch.object(mod, name, lambda _n=name: self.tmp / f'{_n}.sqlite3')
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(mod, 'open_meter', return_value=self.meter)
        p.start()
        self.addCleanup(p.stop)
        self.app = mod.App(self.hn.root, demo=False)
        self.hn.root.show()
        self.hn.root.activateWindow()
        self.app.asset.set('A-8846'); self.app.serial.set('S-1'); self.app.tech.set('T')
        self.app.connect()

    def yes(self):
        return lambda dlg: self.press(dlg, 'Yes')

    def password(self, text, shown):
        from PySide6.QtWidgets import QLineEdit

        def handler(dlg):
            e = dlg.findChild(QLineEdit)
            shown.append(e.echoMode())
            e.setText(text)
            self.press(dlg, 'OK')
        return handler

    def test_unlock_and_relock_password_dialogs_are_masked_and_nothing_leaks(self):
        from PySide6.QtWidgets import QLineEdit
        self.assertEqual(self.app.ui_view.__name__, 'fluke8846a_adjust_view_qt')
        run_dialogs(self.app.start, [self.yes(), lambda dlg: self.press(dlg, 'OK')])        # 'Start new record', then the reset notice
        self.assertIsNotNone(self.app.run_id)
        echo = []
        run_dialogs(self.app.unlock, [self.yes(), self.password('Pw12', echo)])
        self.assertTrue(self.app.unlocked)
        self.assertEqual(echo, [QLineEdit.EchoMode.Password])
        self.pump()                                           # the closed password dialog is deleted
        self.assertNotIn('Pw12', window_text(self.hn.root))
        self.assertNotIn('Pw12', self.app.status.get() + self.app.next_hint.get() + self.app.detail.get())
        run_dialogs(self.app.disconnect, [self.password('Pw12', echo)])
        self.assertEqual(echo, [QLineEdit.EchoMode.Password] * 2)
        self.assertFalse(self.app.unlocked)
        self.assertIn('lock', self.meter.calls)
        self.pump()
        self.assertNotIn('Pw12', window_text(self.hn.root))

    def test_escape_on_the_password_dialog_leaves_the_calibration_locked(self):
        run_dialogs(self.app.start, [self.yes(), lambda dlg: self.press(dlg, 'OK')])
        run_dialogs(self.app.unlock, [self.yes(), lambda dlg: dlg.reject()])
        self.assertFalse(self.app.unlocked)
        self.assertNotIn('unlock', self.meter.calls)
        self.assertEqual(self.app.pill_lock.text(), 'Calibration LOCKED')

    def test_refusing_the_authority_question_does_not_ask_for_the_password(self):
        run_dialogs(self.app.start, [self.yes(), lambda dlg: self.press(dlg, 'OK')])
        run_dialogs(self.app.unlock, [lambda dlg: self.press(dlg, 'No')])
        self.assertFalse(self.app.unlocked)

    def test_declining_the_reset_notice_starts_no_record(self):
        run_dialogs(self.app.start, [self.yes(), lambda dlg: self.press(dlg, 'Cancel')])
        self.assertIsNone(self.app.run_id)
        self.assertEqual(self.app.pill_run.text(), 'No adjustment record')


if __name__ == '__main__':
    unittest.main()
