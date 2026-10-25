"""Headless Qt harness for the bench verification engines (QT-G1a).  Not a test module.

The scenarios of tests/ui_prompt_capture*.py (the same ones that recorded tests/golden_ui/*.json from the Tk build) take a `make_harness(answers)`; QtHarness is one
that runs the REAL engine through the Qt view (`<name>_view_qt`) in an offscreen QMainWindow, with the real QtUiPort for everything about windows, threads and timers
(`post`, `after`, `call_from_worker`, `bind_key`, `on_close`, `var`, `view`, `surprise_handler`), and the scripted operator of ui_prompt_capture for the prompts: a
QtUiPort whose dialog methods (message boxes, yes/no, text/number, file choosers, operator prompts, report details) are answered and recorded by the same Answers rules
as the Tk build's ScriptedUiPort.  (The Qt dialogs themselves are exercised, with an auto-clicking operator, by tests/test_ui_port_qt.py.)

NOTE: the engines' Tk-level recorders patch `time.sleep` (drivers.fluke_5790b.time) to a no-op while a harness is started: wait with QTest.qWait, never time.sleep.

Differences from the Tk harness that the scenarios do not mind: the window is real (the table is a real table, `a.tree.selection` is the real call, made settable the way
the scenarios use it); the pump runs the Qt event loop until the engine is idle and its worker thread has finished.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'Procedures'))

if 'tkinter' not in sys.modules:                       # the engines' Tk-level recorders patch the stub modules (the venv's real tkinter has no display)
    sys.modules['tkinter'] = None
import _tk_stub  # noqa: E402

_tk_stub.install()
import ui_prompt_capture as C  # noqa: E402  (installs the tkinter stub through virtual_harness)
import ui_port  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

import ui_port_qt  # noqa: E402
from qtui import app as qapp  # noqa: E402
from qtui import shell_helpers as H  # noqa: E402

PROMPT_METHODS = ('message', 'ask_yes_no', 'ask_ok_cancel', 'ask_retry_cancel', 'ask_yes_no_cancel', 'ask_text', 'ask_number', 'choose_file', 'save_file', 'choose_dir',
                  'operator_prompt', 'report_details', 'ask_reading', 'ask_readings')


class HybridPort(ui_port_qt.QtUiPort):
    """QtUiPort with the dialog methods answered by a ScriptedUiPort (recording the canonical prompt records)."""

    def __init__(self, scripted):
        super().__init__()
        self.scripted = scripted

    @property
    def prompts(self):
        return self.scripted.prompts

    @property
    def answers(self):
        return self.scripted.answers


def _delegate(name):
    def call(self, *a, **k):
        return getattr(self.scripted, name)(*a, **k)
    call.__name__ = name
    return call


for _n in PROMPT_METHODS:
    setattr(HybridPort, _n, _delegate(_n))


class _Selection:
    """`a.tree.selection.return_value = ()` (the scenarios stub the Tk table that way): a call that answers the real selection unless a value was set."""

    def __init__(self, tree):
        self.tree = tree

    @property
    def return_value(self):
        return self.tree.__dict__.get('_selection_override')

    @return_value.setter
    def return_value(self, v):
        self.tree.__dict__['_selection_override'] = tuple(v)

    def __call__(self):
        ov = self.tree.__dict__.get('_selection_override')
        return ov if ov is not None else self.tree._real_selection()


class QtHarness(C.TkLevelHarness):
    def __init__(self, answers=None, home=None):
        super().__init__(answers, home)
        qapp.create_app()
        self.root = QMainWindow()
        self.root.setProperty('harness', True)

    def start(self):
        super().start()
        from qtui.shell_helpers import ResultsTree
        if not hasattr(ResultsTree, '_real_selection'):
            ResultsTree._real_selection = ResultsTree.selection
        p = mock.patch.object(ResultsTree, 'selection', property(lambda tree: _Selection(tree)))
        p.start()
        self.patches.append(p)
        self.port = HybridPort(C._HarnessPort(self.answers, self))
        self._old_ui = ui_port.set_ui(self.port)
        return self

    def stop(self):
        ui_port.set_ui(self._old_ui)
        try:
            self.root.close()
            self.root.deleteLater()
        except RuntimeError:
            pass
        super().stop()
        for _ in range(3):
            QApplication.processEvents()

    # ---- running ------------------------------------------------------------------------------------------------------------------
    def pump(self, seconds=180):
        end = time.time() + seconds
        app = self.app
        quiet = 0
        while time.time() < end:
            QApplication.processEvents()
            workers = [t for t in threading.enumerate() if t is not threading.main_thread() and t.daemon and t.is_alive()]
            if workers or app.busy:
                quiet = 0
                QTest.qWait(2)
                continue
            quiet += 1
            if quiet > 6:                              # the last posted callbacks (and the 30 ms `after`s) have run
                break
            QTest.qWait(20)
        return not app.busy

    def run_all(self):
        self.app.run_all()
        return self.pump()


def make(answers=None):
    return QtHarness(answers)


# ---------------------------------------------------------------------------------------------------------------------------------------
# helpers shared by the tests and the screenshot script
# ---------------------------------------------------------------------------------------------------------------------------------------
def points_of(app):
    """The points of the app's engine (the 34401A / 8846A launchers have no active_points)."""
    if hasattr(app, 'active_points'):
        return app.active_points()
    return sys.modules[type(app).__module__].POINTS


def record_failures(app, count=6, every=9):
    """Out-of-limit readings for `count` points (every `every`-th), through the engine's own _record, so the table shows FAIL rows."""
    pts = points_of(app)
    done = []
    for p in pts[2::every][:count]:
        app._record(p, p['nominal'] + 3 * p['error'] + (p['error'] or 1), True)
        done.append(str(p['id']))
    return done


def show(win, width=1700, height=840):
    """Resize (after the app fitted the window to the 800 x 600 offscreen screen), show, let the layout settle."""
    win.resize(width, height)
    win.show()
    QTest.qWait(60)


def shot(win, path):
    QTest.qWait(300)                                  # the wrapped detail text and the section rows settle a few event-loop turns after a change
    win.grab().save(str(path))
