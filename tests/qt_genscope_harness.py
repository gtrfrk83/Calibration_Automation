"""Harness for the Qt windows of the function generators and scopes (tests/test_qt_views_genscope.py).  Not a test module; imports PySide6.

`QtHarness` has the shape of tests/ui_prompt_capture's harnesses (`start`, `stop`, `root`, `port`, `answers`, `prompts`, `app`, `pump`, `pump_poll`), so the SAME prompt
scenarios that were recorded on the Tk build (tests/ui_prompt_capture_wpg.py) run unchanged on the real engine behind the REAL Qt window code:

  * the engine App is built on a real QMainWindow (offscreen) with fgen_view_qt / mdo4000c_view_qt / tds2000c_view_qt,
  * the windows' timers, `port.post`, worker threads and `call_from_worker` are the real QtUiPort ones,
  * only the modal dialogs are scripted (`QtScriptedPort`: the scripted operator of ScriptedUiPort answers and records each prompt in the canonical form),
  * the simulated bench is the same as the Tk-level harness's (tests/virtual_harness.VHarness: temp home, sleep patches).
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
sys.path.insert(0, str(ROOT / 'Procedures'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import shiboken6  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

try:                                   # the Tk-level harness patches tkinter's dialog modules: with a real tkinter around (a venv) they must be imported first
    import tkinter.filedialog, tkinter.messagebox, tkinter.simpledialog  # noqa: E401,F401
except ImportError:                    # no tkinter: tests/_tk_stub.py (installed by virtual_harness) stands in
    pass
import labregistry  # noqa: E402
import ui_port  # noqa: E402
import ui_port_qt  # noqa: E402
import virtual_harness as VH  # noqa: E402
from qtui import app as qapp  # noqa: E402
from ui_port import Answers, ScriptedUiPort  # noqa: E402

_REAL_ATTACH = labregistry.attach           # the Tk-level harness replaces it by a mock; the Qt window's asset-history helper must really run

_SCRIPTED = ('message', 'ask_yes_no', 'ask_ok_cancel', 'ask_retry_cancel', 'ask_yes_no_cancel', 'ask_text', 'ask_number', 'choose_file', 'save_file', 'choose_dir',
             'operator_prompt', 'report_details', 'ask_value')


class QtScriptedPort(ui_port_qt.QtUiPort):
    """QtUiPort whose DIALOGS are the scripted operator's (recorded in ui_port's canonical form); everything else (timers, post, worker hand-off, windows,
    variables, `view`) is the real Qt implementation."""

    def __init__(self, answers=None):
        super().__init__()
        self.answers = answers or Answers()
        self.prompts = []
        self.events = []

    _ask = ScriptedUiPort._ask


for _n in _SCRIPTED:
    setattr(QtScriptedPort, _n, getattr(ScriptedUiPort, _n))


class _Selection:
    """tree.selection() that also takes `.return_value = ...` like the Mock the Tk-level scenarios assign (until then it is the real table's selection)."""
    _UNSET = object()

    def __init__(self, real):
        self.real, self.return_value = real, self._UNSET

    def __call__(self):
        return self.real() if self.return_value is self._UNSET else self.return_value


def settle(n=4):
    for _ in range(n):
        QApplication.processEvents()


def workers():
    return [t for t in threading.enumerate() if t is not threading.main_thread() and t.daemon and t.is_alive()]


class QtHarness(VH.VHarness):
    """The Tk-level virtual harness (simulated bench, temp home, speed patches), with a real Qt window and the Qt port instead of FakeRoot."""

    def __init__(self, answers=None, home=None):
        super().__init__(home)
        self.answers = answers or Answers()
        self.prompts = []                 # prompts that bypass the port (must stay empty)
        self._app = None
        self.root = None
        self.port = None

    def start(self):
        super().start()
        keep = mock.patch.object(labregistry, 'attach', _REAL_ATTACH)
        keep.start()
        self.patches.append(keep)
        self.qapp = qapp.create_app()
        self.port = QtScriptedPort(self.answers)
        self._old_ui = ui_port.set_ui(self.port)
        self.root = QMainWindow()
        self.root.resize(1320, 840)
        return self

    def stop(self):
        try:
            if self.root is not None:
                self.root.setProperty('_calsuite_closing', True)
                settle()                           # singleShot(0) calls of the shell run before the window goes
                self.root.close()
                shiboken6.delete(self.root)        # its timers go with it (the MDO / TDS pump re-arms itself for ever)
                self.root = None
        finally:
            ui_port.set_ui(self._old_ui)           # last: a timer that fires while the window goes still finds the Qt port
            super().stop()

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self, a):
        self._app = a
        if a is not None and hasattr(a, 'tree') and hasattr(a.tree, 'selection'):
            a.tree.selection = _Selection(a.tree.selection)          # the scenarios script `a.tree.selection.return_value` (a Tk Treeview mock there)

    def pump(self, seconds=120):
        """Process the window's events until the run is over (not busy, no worker thread left)."""
        end = time.time() + seconds
        app = self._app
        quiet = 0
        while time.time() < end:
            QApplication.processEvents()
            if not app.busy and not workers():
                quiet += 1
                if quiet > 3:
                    break
            else:
                quiet = 0
                time.sleep(0.002)
        settle()
        return not app.busy

    pump_poll = pump
