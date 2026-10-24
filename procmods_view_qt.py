"""The Qt windows the procedure-modification engine mixin (procmods_engine.ProcModsMixin) attaches: the right-click 'Edit' menu of a point list and the in-run
'Edit point' action.  The window code is qtui/screens/procmods_point_editor.py / procmods_editor.py; this module is the seam
`ui_port.get_ui().view('procmods_view')` the toolkit-free engine mixin uses (the Qt twin of procmods_view_tk).  Both resolve their module at call time (tests patch them)."""
from __future__ import annotations


def attach_tree_menu(app, tree, resolver=None):
    from qtui.screens import procmods_point_editor
    return procmods_point_editor.attach_tree_menu(app, tree, resolver)


def attach_live(app, shell, *args, **kwargs):
    from qtui.screens import procmods_editor
    return procmods_editor.attach_live(app, shell, *args, **kwargs)
