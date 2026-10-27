"""Tk twin of field_uncertainty_view_qt.py: there is no Tk window for the 'Assign uncertainty' panel (it is a Qt screen), so the Tk build adds nothing to a procedure window.
Report writing and the stored assignments are toolkit-free and work in both builds."""
from __future__ import annotations


def attach(app, shell, *args, **kwargs):
    return None
