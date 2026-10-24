"""Qt screens (one module per screen).  The Manager (manager.py) hosts the panels other modules provide.

PANELS is the registry of the Manager's hosted tabs: key -> 'module:Class', imported lazily (`load_panel`).  APPEND-ONLY: every panel module adds its line
here when it is built; the constructors mirror the Tk ones (`Panel(parent, on_saved=None, status=None)`).  A module that does not exist yet is not an error:
the Manager shows a 'not built yet' placeholder in that tab.
"""
from __future__ import annotations

import importlib

PANELS = {
    'asset_history': 'qtui.screens.asset_history:AssetHistoryPanel',
    'standards_specs': 'qtui.screens.standards_specs:StandardsSpecsPanel',
    'datasheet_builder': 'qtui.screens.datasheet_builder:DatasheetBuilderPanel',
}


def load_panel(key: str):
    """The panel class registered under `key`.  Raises ImportError / AttributeError / KeyError when it cannot be had (the caller shows a placeholder)."""
    module, _, cls = PANELS[key].partition(':')
    return getattr(importlib.import_module(module), cls)
