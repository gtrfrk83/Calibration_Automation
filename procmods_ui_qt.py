"""Qt twin of procmods_ui.py: the procedure editor window.  The window code is qtui/screens/procmods_editor.py; this module is the import point
procmods_view_qt resolves at call time (attach_live(app, shell, ...))."""
from __future__ import annotations

from qtui.screens.procmods_editor import (LiveHook, ModifyWindow, ShellHook, UnlockDialog, ask_unlock, attach_live, attach_to_shell,   # noqa: F401
                                          open_manager_changes, open_modify_window, shared_lock)
