"""Where the suite keeps its data (databases, saved progress), kept apart from the program files.

Why: a program folder is often read-only, shared, or replaced on update; saved results must survive that.  Each person gets their own
data folder, e.g.  C:\\Users\\<name>\\AppData\\Local\\CalibrationSuite-Beta\\

    <data folder>\\calibration_procedures.sqlite3   (the Manager's database; its schema is never changed by this module)
    <data folder>\\lab_registry.sqlite3
    <data folder>\\progress\\...                    (saved progress / checkpoint files)

Rules this module follows:
  * It only COPIES.  Nothing in the program folder or in another copy of the suite is moved, changed or deleted.
  * CALSUITE_DATA (environment variable) chooses the data folder explicitly.
  * An empty file named portable.txt beside the program keeps the old layout (data next to the program), e.g. for a USB stick.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import suite_info

HERE = Path(__file__).resolve().parent
DB_NAMES = ('calibration_procedures.sqlite3', 'lab_registry.sqlite3')


def is_portable() -> bool:
    return (HERE / 'portable.txt').exists()


def data_dir() -> Path:
    env = os.environ.get('CALSUITE_DATA', '').strip()
    if env:
        folder = Path(env).expanduser()
    elif is_portable():
        folder = HERE
    else:
        if sys.platform.startswith('win'):
            base = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
        else:
            base = Path(os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local' / 'share'))
        name = 'CalibrationSuite' + ('-' + suite_info.EDITION.split()[0] if suite_info.EDITION else '')
        folder = base / name
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = HERE                              # cannot create it: fall back to beside the program rather than fail
    return folder


def db_path(name: str) -> Path:
    return data_dir() / name


def progress_path(name: str) -> Path:
    """Saved-progress (checkpoint) file.  Portable mode keeps the old place, Procedures\\."""
    if data_dir() == HERE:
        return HERE / 'Procedures' / name
    folder = data_dir() / 'progress'
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return HERE / 'Procedures' / name
    return folder / name


def import_from(folder, log=None) -> list[str]:
    """Copy the databases and saved progress of another copy of the suite (a folder that holds calibration_procedures.sqlite3 ...)
    into this data folder.  A file that already exists here is first saved as <name>.before-import-<date>.  The source is not touched.
    Returns the names copied."""
    src = Path(folder)
    dest = data_dir()
    if src.resolve() == dest.resolve():
        return []
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    copied = []

    def put(source: Path, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copy2(target, target.with_name(target.name + f'.before-import-{stamp}'))
        shutil.copy2(source, target)
        copied.append(target.name)
        if log:
            log(f'copied {source} -> {target}')

    for name in DB_NAMES:
        if (src / name).is_file():
            put(src / name, dest / name)
    for pattern_dir in (src / 'Procedures', src / 'progress'):
        if pattern_dir.is_dir():
            for f in sorted(pattern_dir.glob('*checkpoint*.json')):
                put(f, progress_path(f.name))
    return copied


def migrate_legacy_progress() -> int:
    """First start with a separate data folder: bring along progress files that older versions saved in Procedures\\ (copy only, and only
    when no copy exists yet in the data folder).  The databases are NOT copied here; use import_from() / the Help menu for those."""
    if data_dir() == HERE:
        return 0
    n = 0
    legacy = HERE / 'Procedures'
    if legacy.is_dir():
        for f in legacy.glob('*checkpoint*.json'):
            target = progress_path(f.name)
            if not target.exists():
                try:
                    shutil.copy2(f, target)
                    n += 1
                except OSError:
                    pass
    return n
