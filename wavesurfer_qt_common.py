"""WaveSurfer 4104HD Qt window: the small pieces every part of the window code shares (helper of wavesurfer_view_qt.py; no instrument, no pass / fail logic).

  * `WindowGone` / `need(widget)`: Tk raised `tk.TclError` for a widget of a destroyed window and the engine's two periodic ticks stop on it; Qt raises a plain
    `RuntimeError` ('Internal C++ object already deleted') for any deleted object, so the view turns a dead widget into this one class and `window_gone()` returns
    it: the ticks stop for a closed window and a genuine RuntimeError from the engine is never swallowed.
  * `page(self, title)`: one section page of the notebook that holds each section's widgets (the notebook is never shown, as in Tk).
  * the Treeview-like helpers the engine reaches through the view (`set_grid`, `selection`, `row_index`, ...), the section tables and progress bars.
No Tk import (tests/test_qtui_rules.py scans qtui/ only; this file keeps the same rule)."""
from __future__ import annotations

import shiboken6
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QSizePolicy, QVBoxLayout, QWidget

import qtui.shell_helpers as H
from qtui.shell import _result_tones


class WindowGone(RuntimeError):
    """A widget of a window that was closed (the Qt twin of tk.TclError for the periodic ticks)."""


def alive(widget) -> bool:
    return widget is not None and shiboken6.isValid(widget)


def need(widget):
    """The widget itself, or WindowGone when its window has been destroyed."""
    if not alive(widget):
        raise WindowGone('window closed')
    return widget


def guarded(fn):
    """Run `fn()`; a RuntimeError caused by a deleted Qt object becomes WindowGone, any other error passes unchanged."""
    try:
        return fn()
    except WindowGone:
        raise
    except RuntimeError as exc:
        if 'already deleted' in str(exc) or 'Internal C++ object' in str(exc):
            raise WindowGone(str(exc)) from exc
        raise


# ---- layout helpers ---------------------------------------------------------------------------------------------------------------------------------
def row(*widgets, spacing: int = 8, stretch_end: bool = True) -> QWidget:
    """A horizontal line of widgets (Tk: frame with side='left' children)."""
    box = H.frame(None, 'h', spacing=spacing)
    lay = box.layout()
    for w in widgets:
        lay.addWidget(w)
    if stretch_end:
        lay.addStretch(1)
    return box


def text(content: str, style: str | None = None, wrap: bool = True):
    """A plain-text label (ttk.Label with a wraplength): wraps by default so a long note never forces the window wider."""
    lab = H.label_(None, content, style, wraplength=1 if wrap else None)     # wraplength only switches word wrap on (Qt wraps at the available width)
    if wrap:
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lab.setMinimumWidth(10)
    return lab


def page(self, title: str, margins: int = 14):
    """A new page of the (hidden) notebook; returns (page widget, its vertical layout).  The page is the 'tab' the engine hands to set_tab_text."""
    pg = QWidget()
    lay = QVBoxLayout(pg)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(6)
    self.tabs.addTab(pg, title)
    return pg, lay


def hidden_button(owner: QWidget, label_: str, command):
    """A button the engine keeps for state handling but the window never shows ('Manual Next button intentionally not displayed')."""
    b = H.button(owner, label_, command)
    b.hide()
    return b


def progress(maximum: int) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, max(1, int(maximum)))
    bar.setValue(0)
    bar.setTextVisible(False)
    return bar


def section_tree(columns, headings, widths, *, height: int = 10):
    """The table of one section: the Treeview calls of the engine (insert / item / selection / ...) work on it; the Result column takes the pass / fail colour."""
    tree = H.make_table(None, columns, headings, widths, height=height, pack_=False)
    if 'result' in columns:
        _result_tones(tree)
    return tree


def labelled_entry(label_: str, var, width: int = 8):
    return [H.label_(None, label_), H.entry(None, var, width=width)]


def hbox_widgets(parent_layout, widgets, spacing: int = 6):
    h = QHBoxLayout()
    h.setSpacing(spacing)
    for w in widgets:
        h.addWidget(w)
    h.addStretch(1)
    parent_layout.addLayout(h)
    return h


# ---- the Treeview calls the engine makes through the view ----------------------------------------------------------------------------------------------
def selection(tree):
    return tree.selection()


def children(tree):
    return tree.get_children()


def row_index(tree, iid):
    return list(tree.get_children()).index(iid)


def select(tree, iid):
    tree.selection_set(iid)


def select_and_show(tree, iid):
    tree.selection_set(iid)
    tree.see(iid)


def set_grid(tree, items, active=None):
    """items = [(values, tags), ...].  Updates rows in place, keeps the selection, scrolls to `active` (the Tk view's `set_grid`, same arithmetic)."""
    sel = tree.selection()
    keep = list(tree.get_children()).index(sel[0]) if sel else None
    ids = list(tree.get_children())
    if len(ids) != len(items):
        ids = [f'i{k}' for k in range(len(items))]
        tree.set_all([(iid, values, tags) for iid, (values, tags) in zip(ids, items)])
    else:
        for iid, (values, tags) in zip(ids, items):
            old = tree._by_iid[iid]
            tags = tuple(tags) if isinstance(tags, (tuple, list)) else (tags,)
            if list(old.values) != list(values) or tuple(old.tags) != tags:
                tree.item(iid, values=values, tags=tags)
    if keep is not None and keep < len(ids):
        tree.selection_set(ids[keep])
    if active is not None and ids:
        tree.see(ids[min(active + 3, len(ids) - 1)])      # keep a few finished rows in view above it
        tree.see(ids[min(active, len(ids) - 1)])
    return ids


def point_menu(app, tree, prefix: str):
    """Right-click > Edit for a section table: `resolver(iid)` names the point 'prefix:index' (tolerance only here), as the Tk view's lambda did."""
    app.pm_bind_tree(tree, lambda iid, t=tree: '%s:%d' % (prefix, row_index(t, iid)))
