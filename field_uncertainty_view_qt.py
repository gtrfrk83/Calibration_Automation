"""The Qt side of the in-run 'No uncertainty: Assign' call to action (field_uncertainty.py; the panel is qtui/screens/field_uncertainty_panel.py).

procmods_engine.ProcModsMixin.pm_live_attach(shell) calls `ui.view('field_uncertainty_view').attach(app, shell)` once the procedure window is built.  The hook looks at the
points the run has recorded (the same rows the report is built from) every few seconds and, only when a point that should carry an uncertainty has none, adds ONE small button
to the window's action bar: 'No uncertainty: Assign'.  Nothing is added to a window that has nothing missing.  The button never blocks the run, never changes pass / fail, a limit,
a command or a prompt; the panel it opens is modal only over its own window.
"""
from __future__ import annotations

POLL_MS = 4000
LABEL = 'No uncertainty: Assign'


class FieldHook:
    def __init__(self, app, shell, poll_ms=POLL_MS):
        self.app, self.shell = app, shell
        self.button = None
        self.count = 0
        self._sig = None
        self.timer = None
        try:
            from PySide6.QtCore import QTimer
            root = getattr(shell, 'root', None)
            self.timer = QTimer(root) if root is not None and hasattr(root, 'metaObject') else QTimer()
            self.timer.setInterval(poll_ms)
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
        except Exception:
            self.timer = None

    def _recorded(self):
        """A cheap signature of what the run has recorded, so the rows are rebuilt only when something new arrived."""
        sig = []
        for name in ('found', 'results', 'left', 'readings', 'records'):
            store = getattr(self.app, name, None)
            try:
                sig.append(len(store) if store is not None else None)
            except TypeError:
                sig.append(None)
        return tuple(sig)

    def refresh(self, force=False) -> int:
        """Re-count the recorded points that should carry an uncertainty and have none; show / hide the button.  Never raises."""
        try:
            root = getattr(self.shell, 'root', None)
            if root is not None and hasattr(root, 'isVisible') and not root.isVisible() and not force:
                return self.count
            sig = self._recorded()
            if not force and sig == self._sig and None not in sig:
                return self.count
            self._sig = sig
            from qtui.screens import field_uncertainty_panel as P
            self.count = P.missing_count(self.app)
            if self.count and self.button is None:
                self.button = self.shell.add_action(LABEL, self.open, short='Assign')
                self.button.setObjectName('field_assign_button')
            if self.button is not None:
                self.button.setVisible(bool(self.count))
                self.button.setToolTip(f'{self.count} recorded point(s) should carry an uncertainty and have none. Assign a suggested value or enter your own. '
                                       'The run, pass / fail and the limits are not affected.')
        except Exception:
            pass
        return self.count

    def open(self):
        from qtui.screens import field_uncertainty_panel as P
        out = P.open_for_app(getattr(self.shell, 'root', None), self.app)
        self.refresh(force=True)
        return out


def attach(app, shell, *args, **kwargs):
    return FieldHook(app, shell, *args, **kwargs)
