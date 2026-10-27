"""The run queue's windows for Qt (port of the removed Tk view run_queue_view_tk.py; same public functions).  The thin seam `ui_port.get_ui().view('run_queue_view')` the toolkit-free
engine (run_queue_engine.py) uses, plus the 'Several meters' block of the Connections drawer.

  * `build_queue_drawer(self, d, row)`   native here.  `d` is the drawer's QGridLayout (or a widget that has one); the block takes rows row .. row+2 of its two
                                         columns, exactly as the Tk grid does, and returns the next free row.  `self.btn_queue` is the 'Run queue...' button
                                         (calls self.open_queue_setup), `self.queue_label` a variable with get / set (the muted line under it).
  * `ask_queue_setup(...)`, `queue_progress(...)`   the queue set-up window and the progress window are window code of run_queue_ui.py, ported by package QT-E as
                                         `run_queue_ui_qt.py` (ask_queue_setup(parent, title, meters, mode, summarize, status_of=, candidates=, default_tech=, ir_only=),
                                         class QueueProgress(parent, title=, on_show=, on_export=)).  They are resolved at call time, like the Tk seam, so a test that
                                         patches run_queue_ui_qt.ask_queue_setup still takes effect.  Until that module exists they raise ImportError (the
                                         engine's callers already treat an unavailable window as 'cannot open')."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QPushButton

from datamode_view_qt import QtVar
from qtui.widgets import label, rule


def ask_queue_setup(*args, **kwargs):
    import run_queue_ui_qt
    return run_queue_ui_qt.ask_queue_setup(*args, **kwargs)


def queue_progress(*args, **kwargs):
    import run_queue_ui_qt
    return run_queue_ui_qt.QueueProgress(*args, **kwargs)


def build_queue_drawer(self, d, row):
    """The 'Run queue' area of the Connections drawer (rows row .. row+2).  Returns the next free row."""
    grid = d if isinstance(d, QGridLayout) else d.layout()
    parent = None if isinstance(d, QGridLayout) else d
    sep = rule()
    sep.setFixedHeight(1)
    grid.addWidget(sep, row, 0, 1, 2)
    grid.setRowMinimumHeight(row, 12)
    grid.addWidget(label('Several meters', 'section', parent=parent), row + 1, 0, Qt.AlignmentFlag.AlignLeft)
    self.btn_queue = QPushButton('Run queue...')
    self.btn_queue.clicked.connect(lambda _c=False: self.open_queue_setup())
    grid.addWidget(self.btn_queue, row + 1, 1, Qt.AlignmentFlag.AlignLeft)
    self.queue_label = QtVar('No queue: one meter, as usual.')
    text = label(self.queue_label.get(), 'sub', wrap=True)
    text.setMaximumWidth(340)
    self.queue_label.trace_add('write', lambda *_: text.setText(self.queue_label.get()))
    grid.addWidget(text, row + 2, 0, 1, 2)
    self.queue_label_widget = text
    return row + 3
