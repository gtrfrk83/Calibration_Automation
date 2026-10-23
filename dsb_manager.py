"""Datasheet Builder: how the Manager lists and launches user-built datasheets (no tkinter, no instrument I/O).

A saved datasheet is a runnable spec file in the data folder (datasheet_builder.save) plus a row in lab_registry.sqlite3.  The Manager's
Procedures table is read from calibration_procedures.sqlite3, whose schema and contents are never touched here.  Instead of writing a row per
datasheet into that database (stale rows, a second place to keep in step), the Manager ADDS the user-built rows to the list it shows:

    rows = dsb_manager.user_rows()          # one dict per runnable datasheet, iid 'ds:<uid>', category 'User-built', tag 'user-built'
    args = dsb_manager.launch_args(row, demo=False, asset=None)     # [python, Procedures/User_Datasheet.py, --spec, <spec file>, ...]

Every row launches the same generic launcher, Procedures/User_Datasheet.py, with the datasheet's spec file; the launcher starts dsb_runtime.
A datasheet that is deleted or has no runnable version has no row.  Nothing here raises: a damaged registry or folder gives an empty list.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
LAUNCHER = 'Procedures/User_Datasheet.py'
TAG = 'user-built'
IID_PREFIX = 'ds:'


def is_user_iid(iid) -> bool:
    return str(iid).startswith(IID_PREFIX)


def user_rows(root=None, db=None) -> list:
    """[{iid, name, manufacturer, model, category, tag, script, spec_path, version, status, uid, description}] for the Procedures list."""
    try:
        import datasheet_builder
        entries = datasheet_builder.procedure_entries(root=root, db=db)
    except Exception:
        return []
    out = []
    for e in entries:
        out.append(dict(iid=IID_PREFIX + e['uid'], name=e['name'], manufacturer=e.get('manufacturer', ''), model=e.get('model', ''),
                        category=e.get('category') or 'User-built', tag=e.get('tag') or TAG, script=LAUNCHER, spec_path=e['spec_path'],
                        version=e.get('version'), status=e.get('status', ''), uid=e['uid'],
                        description=f'User-built datasheet (Datasheet Builder), saved version {e.get("version")}'
                                    + ('' if e.get('status') in (None, '', 'ready') else f' - {e.get("status")}')))
    return out


def launch_args(row, demo=False, asset=None, python=None) -> list:
    """The command line that runs one user-built row."""
    args = [python or sys.executable, str(BASE / LAUNCHER), '--spec', str(row['spec_path'])]
    if demo:
        args.append('--demo')
    if asset:
        args += ['--asset', asset]
    return args


def launch_process(row, demo=False, asset=None, python=None, popen=None):
    """Start one user-built row in its own process, the way the Manager does (`Calibration_Procedure_Manager._launch`): the generic launcher with the spec
    file, working directory = Procedures/.  `demo` adds only --demo (the virtual bench).  Returns the process; raises OSError when it cannot start."""
    import subprocess
    return (popen or subprocess.Popen)(launch_args(row, demo=demo, asset=asset, python=python), cwd=str(BASE / 'Procedures'))


def status_text(row, found=True) -> str:
    return ('Ready' if found else 'Missing') + f'  [{TAG}]'
