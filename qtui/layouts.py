"""Remembered window layouts (size, position, splitter positions, which panels are open), one small JSON file per user.

    layouts.restore('manager', window)            # right after the window is built; does nothing when nothing was saved
    layouts.save('manager', window, extra={...})  # from closeEvent
    layouts.reset('manager')                      # forget one window's layout (or reset() for all)

The file is <data folder>/window_layouts.json (appdata.data_dir()); it is NOT part of calibration_procedures.sqlite3 or the lab registry.  Anything wrong with it
(missing, unreadable, damaged, a position now off-screen) means "use the defaults": a layout can never stop a window opening.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

FILE_NAME = 'window_layouts.json'


def enabled() -> bool:
    """CALSUITE_LAYOUTS=0 turns remembering off (the test-suite does, so one test's window size never leaks into another)."""
    return os.environ.get('CALSUITE_LAYOUTS', '1') != '0'


def path() -> Path:
    import appdata
    return appdata.data_dir() / FILE_NAME


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> bool:
    target = path()
    tmp = target.with_name(target.name + '.tmp')
    try:
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding='utf-8')
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def _b64(raw) -> str:
    return base64.b64encode(bytes(raw)).decode('ascii')


def save(name: str, window, splitters: dict | None = None, extra: dict | None = None) -> bool:
    """Remember `window` (geometry, maximised state) and the named splitters; `extra` is any small JSON-able dict (e.g. which sections are open)."""
    if not enabled():
        return False
    entry = {'geometry': _b64(window.saveGeometry())}
    if splitters:
        entry['splitters'] = {k: _b64(s.saveState()) for k, s in splitters.items()}
    if extra:
        entry['extra'] = extra
    data = _load()
    data[name] = entry
    return _write(data)


def saved(name: str) -> dict:
    entry = _load().get(name)
    return entry if isinstance(entry, dict) else {}


def restore(name: str, window, splitters: dict | None = None) -> dict:
    """Put the saved layout back.  Returns the `extra` dict that was saved ({} if none), so the caller can re-apply its own bits."""
    from PySide6.QtCore import QByteArray
    entry = saved(name) if enabled() else {}
    if not entry:
        return {}
    try:
        if entry.get('geometry'):
            window.restoreGeometry(QByteArray(base64.b64decode(entry['geometry'])))
        for key, s in (splitters or {}).items():
            raw = (entry.get('splitters') or {}).get(key)
            if raw:
                s.restoreState(QByteArray(base64.b64decode(raw)))
    except (ValueError, TypeError):
        return {}
    extra = entry.get('extra')
    return extra if isinstance(extra, dict) else {}


def reset(name: str | None = None) -> bool:
    if name is None:
        data = {}
    else:
        data = _load()
        data.pop(name, None)
    return _write(data)
