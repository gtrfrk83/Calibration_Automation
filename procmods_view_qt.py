"""The Qt windows the procedure-modification engine mixin (procmods_engine.ProcModsMixin) attaches (twin of procmods_view_tk.py; same public functions):
the right-click 'Edit' menu of a point list and the in-run 'Edit procedure' action.  Reached through ui_port.get_ui().view('procmods_view').

  * `attach_tree_menu(app, tree, resolver=None)`   native here.  `tree` is a qtui.table.DataTable (its `context_provider` hook; `resolver(iid)` gets the row's
        key, `DataTable.row_key(row)`, which is the point id in every engine's list) or any QAbstractItemView (`resolver` gets the QModelIndex).  The menu is
        'Edit' (disabled with the reason shown under it, cut at 90 characters, on a verified / locked procedure and while the point is being measured:
        procmods_point_model.menu_state, unchanged) followed by the engine's own entries (app.tree_menu_extras(pid): [(label, command, enabled, why)]) each after a
        separator.  Right-click selects the row first.  Returns a TreeMenu (`entries(pid)` = what the menu holds, for tests and the keyboard menu key).
  * Edit opens the point window, which is window code of procmods_point_ui.py: resolved at call time as `procmods_point_ui_qt.open_point_window(app, pid, lock=)`;
    `attach_live` likewise as `procmods_ui_qt.attach_live(app, shell)`.  Those two Tk-only modules (about 1,650 lines of editor windows) are not ported by this
    package; until they exist the calls raise ImportError (pm_live_attach already turns that into a warning, never a broken window)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QMenu

import procmods_point_model as PM


class TreeMenu:
    """The right-click menu of one point list."""

    def __init__(self, app, tree, resolver, lock=None):
        self.app, self.tree, self.lock = app, tree, lock
        self.resolve = resolver or (lambda iid: iid)

    def entries(self, pid):
        """[(label, callback or None, enabled)] in menu order; a None callback is a disabled reason line / separator marker ('-')."""
        app = self.app
        enabled, why = PM.menu_state(app, pid)
        out = [('Edit', lambda: open_point_window(app, pid, lock=self.lock), enabled)]
        if not enabled:
            out.append((why[:90] + ('...' if len(why) > 90 else ''), None, False))
        extras = getattr(app, 'tree_menu_extras', None)          # an engine's own entries (manual_override: 'Enter reading manually'); none for every other procedure
        if extras is not None:
            try:
                for label, command, ok, reason in extras(pid):
                    out.append(('-', None, False))
                    out.append((label, command, bool(ok)))
                    if not ok and reason:
                        out.append((reason[:90] + ('...' if len(reason) > 90 else ''), None, False))
            except Exception:
                pass
        return out

    def build(self, pid, parent=None):
        menu = QMenu(parent or self.tree)
        for label, cb, ok in self.entries(pid):
            if label == '-' and cb is None:
                menu.addSeparator()
                continue
            act = menu.addAction(label)
            act.setEnabled(ok)
            if cb is not None:
                act.triggered.connect(lambda _c=False, f=cb: f())
        return menu

    def row_entries(self, row):
        """The context_provider of a DataTable: the menu for the clicked row (the table puts them above its Copy entries)."""
        if row is None:
            return []
        try:
            self.tree.select_rows([row])
            pid = self.resolve(self.tree.row_key(row))
        except Exception:
            return []
        return [e for e in self.entries(pid)]

    def popup(self, pos):
        """Generic QAbstractItemView: pos in viewport coordinates."""
        ix = self.tree.indexAt(pos)
        if not ix.isValid():
            return None
        self.tree.setCurrentIndex(ix)
        menu = self.build(self.resolve(ix))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
        return menu


def open_point_window(app, pid, lock=None, parent=None):
    import procmods_point_ui_qt
    return procmods_point_ui_qt.open_point_window(app, pid, lock=lock, parent=parent)


def attach_tree_menu(app, tree, resolver=None, lock=None):
    tm = TreeMenu(app, tree, resolver, lock)
    if hasattr(tree, 'context_provider'):                       # qtui.table.DataTable
        tree.context_provider = tm.row_entries
    elif isinstance(tree, QAbstractItemView):
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(tm.popup)
    app.__dict__.setdefault('_pm_tree_menus', []).append((tree, tm.resolve))
    return tm


def attach_live(app, shell, *args, **kwargs):
    import procmods_ui_qt
    return procmods_ui_qt.attach_live(app, shell, *args, **kwargs)
