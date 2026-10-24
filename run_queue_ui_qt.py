"""Qt twin of run_queue_ui.py: the same names and contracts (ask_readings, ask_meter, ask_queue_setup, QueueProgress) for the Qt build.  The window code is
qtui/screens/run_queue.py; this module is the import point that keeps the Tk module's public functions available under the same names
(`import run_queue_ui_qt as run_queue_ui`).  Resolved at call time by run_queue_view_qt, so a test that patches run_queue_ui_qt.ask_queue_setup takes effect."""
from __future__ import annotations

from qtui.screens.run_queue import (WIDTH, MeterDialog, QueueProgress, QueueSetupDialog, ReadingsDialog, ask_meter, ask_queue_setup,   # noqa: F401
                                    ask_readings)
