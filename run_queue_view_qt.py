"""The run queue's windows for Qt: the thin seam `ui_port.get_ui().view('run_queue_view')` the toolkit-free engine (run_queue_engine.py) uses, plus the
'Several meters' block of the Connections drawer (the Qt twin of run_queue_view_tk.build_queue_drawer).  The window code is qtui/screens/run_queue.py
(re-exported by run_queue_ui_qt.py); everything resolves run_queue_ui_qt at call time, so a test that patches run_queue_ui_qt.ask_queue_setup still
takes effect."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton

from qtui.widgets import label, rule


def ask_queue_setup(*args, **kwargs):
    import run_queue_ui_qt
    return run_queue_ui_qt.ask_queue_setup(*args, **kwargs)


def queue_progress(*args, **kwargs):
    import run_queue_ui_qt
    return run_queue_ui_qt.QueueProgress(*args, **kwargs)


class _QueueLabel(QLabel):
    """The muted status line of the drawer; the engine writes it with `.set(text)` (run_queue_engine._queue_status)."""

    def set(self, text):
        self.setText(text)


def build_queue_drawer(self, d, row):
    """The 'Run queue' area of the Connections drawer (rows row .. row+2 of the grid `d`: a QGridLayout, or a QWidget that has one).  Returns the next free row."""
    grid = d if isinstance(d, QGridLayout) else d.layout()
    grid.addWidget(rule(), row, 0, 1, 2)
    grid.addWidget(label('Several meters', 'section'), row + 1, 0)
    self.btn_queue = QPushButton('Run queue...')
    self.btn_queue.clicked.connect(lambda _c=False: self.open_queue_setup())
    grid.addWidget(self.btn_queue, row + 1, 1)
    self.queue_label = _QueueLabel('No queue: one meter, as usual.')
    self.queue_label.setProperty('role', 'hint')
    self.queue_label.setWordWrap(True)
    grid.addWidget(self.queue_label, row + 2, 0, 1, 2)
    return row + 3
