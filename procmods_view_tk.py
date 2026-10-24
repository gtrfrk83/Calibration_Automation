"""The Tk windows the procedure-modification engine mixin (procmods_engine.ProcModsMixin) attaches: the right-click 'Edit' menu of a point list and the in-run
'Edit procedure' action.  The window code itself is procmods_point_ui.py / procmods_ui.py (Tk-only modules: the editor windows, tabs and dialogs); this module is the
seam `ui_port.get_ui().view('procmods_view')` the toolkit-free engine mixin uses.  Both resolve their module at call time (tests patch them)."""
from __future__ import annotations


def attach_tree_menu(app, tree, resolver=None):
    import procmods_point_ui
    return procmods_point_ui.attach_tree_menu(app, tree, resolver)


def attach_live(app, shell, *args, **kwargs):
    import procmods_ui
    return procmods_ui.attach_live(app, shell, *args, **kwargs)
