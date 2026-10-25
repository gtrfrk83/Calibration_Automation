"""Soft drop shadows ("depth") on cards and buttons, switchable from Help > Depth (shadows).  Display only: nothing here touches data or instrument code.

    depth.install()                 # once, after the QApplication exists (qtui.app.create_app does this)
    depth.set_enabled(False, save=True)

Where shadows go: buttons (not the flat "ghost" / icon ones, not checkable ones, not inside a table / list) and top-level cards (not a card inside a card, not a card that
holds a table or list, which would be redrawn through the shadow on every scroll).  Menus, tables, grids, text boxes and the live run screens' readings are left flat.
CALSUITE_DEPTH=0 / 1 overrides the saved choice (the test-suite sets 0).  The saved choice lives in the same per-user appearance file as the theme."""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QApplication, QFrame, QGraphicsDropShadowEffect, QMenu, QPushButton, QWidget

_filter = None
_on = None
TAG = '_depth'


def enabled() -> bool:
    env = os.environ.get('CALSUITE_DEPTH', '').strip()
    if env in ('0', '1'):
        return env == '1'
    global _on
    if _on is None:
        try:
            import ui_theme_core as core
            _on = core.Settings('appearance').get('depth', 'soft') != 'flat'
        except Exception:
            _on = True
    return _on


def _in_view(w: QWidget) -> bool:
    p = w.parentWidget()
    while p is not None:
        if isinstance(p, (QAbstractItemView, QMenu)):
            return True
        p = p.parentWidget()
    return False


def _is_card(w) -> bool:
    return isinstance(w, QFrame) and w.property('surface') in ('card',)


def wants_shadow(w) -> str | None:
    """'button' | 'card' | None for a widget."""
    if isinstance(w, QPushButton):
        if w.isCheckable() or w.property('role') in ('ghost', 'icon') or w.property('depth') == 'off' or _in_view(w):
            return None
        return 'button'
    if _is_card(w):
        if w.property('depth') == 'off' or _in_view(w) or w.findChildren(QAbstractItemView):
            return None
        p = w.parentWidget()
        while p is not None:
            if _is_card(p):
                return None
            p = p.parentWidget()
        return 'card'
    return None


def _effect(kind: str, parent) -> QGraphicsDropShadowEffect:
    dark = False
    try:
        from qtui import theme
        dark = theme.is_dark()
    except Exception:
        pass
    e = QGraphicsDropShadowEffect(parent)
    if kind == 'button':
        e.setBlurRadius(9)
        e.setOffset(0, 2)
        e.setColor(QColor(0, 0, 0, 120 if dark else 75))
    else:
        e.setBlurRadius(26)
        e.setOffset(0, 7)
        e.setColor(QColor(0, 0, 0, 85 if dark else 55))
    e.setObjectName(TAG)
    return e


def apply_to(w) -> bool:
    kind = wants_shadow(w)
    if kind is None or (w.graphicsEffect() is not None and w.graphicsEffect().objectName() != TAG):
        return False
    w.setGraphicsEffect(_effect(kind, w))
    return True


def remove_from(w) -> bool:
    e = w.graphicsEffect()
    if e is not None and e.objectName() == TAG:
        w.setGraphicsEffect(None)
        return True
    return False


class _Filter(QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and enabled() and isinstance(obj, (QPushButton, QFrame)) and obj.graphicsEffect() is None:
            apply_to(obj)
        return False


def install(app=None) -> None:
    global _filter
    app = app or QApplication.instance()
    if app is None or _filter is not None:
        return
    _filter = _Filter(app)
    app.installEventFilter(_filter)


def set_enabled(on: bool, save: bool = False) -> None:
    """Switch shadows on or off for every open window at once, and (save=True) remember the choice."""
    global _on
    _on = bool(on)
    if save:
        try:
            import ui_theme_core as core
            store = core.Settings('appearance')
            store.set('depth', 'soft' if on else 'flat')
            store.save()
        except Exception:
            pass
    for w in QApplication.allWidgets():
        if isinstance(w, (QPushButton, QFrame)):
            if on and w.isVisible():
                apply_to(w)
            elif not on:
                remove_from(w)
