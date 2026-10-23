"""The right-click menu of a row of the Manager's Procedures table.  Tk-free; no instrument I/O.

    procedure_menu.items(found=True, verify=('Mark verified on hardware...', True), lock=('Unlock for editing...', False), can_show=True)
        -> [Item(key, label, enabled), ..., None (a separator), ...]

Every entry runs an action the Manager already has (Run procedure, Try in demo mode, Mark verified / Unlock, Restore previous version, Remove from library); only
Copy and Show file location are new, and they change nothing.  The enabled rules are the buttons' own: Run and demo need the script file
(the 'Ready to run' pill), and the two verification entries take the text and state of the card's buttons, so the menu can never offer
what a button refuses.  Restore previous version (the old Procedure Development tab's button) needs a managed script with a saved backup.  Remove from library is always offered because its handler explains why a user-built or locked row stays."""
from collections import namedtuple

Item = namedtuple('Item', 'key label enabled')

RUN, DEMO, VERIFY, LOCK, RESTORE, REMOVE, COPY_NAME, COPY_PATH, SHOW = 'run', 'demo', 'verify', 'lock', 'restore', 'remove', 'copy_name', 'copy_path', 'show'
RUN_LABEL = 'Run procedure'
DEMO_LABEL = 'Try in demo mode (virtual instruments)'
REMOVE_LABEL = 'Remove from library'
RESTORE_LABEL = 'Restore previous version...'


def items(found, verify, lock, can_show, has_path=True, restorable=False):
    """The menu for the selected row.  `verify` / `lock` are (text, enabled) as the card's two buttons show them."""
    return [Item(RUN, RUN_LABEL, bool(found)),
            Item(DEMO, DEMO_LABEL, bool(found)),
            None,
            Item(VERIFY, verify[0], bool(verify[1])),
            Item(LOCK, lock[0], bool(lock[1])),
            None,
            Item(RESTORE, RESTORE_LABEL, bool(restorable)),
            Item(REMOVE, REMOVE_LABEL, True),
            None,
            Item(COPY_NAME, 'Copy procedure name', True),
            Item(COPY_PATH, 'Copy file path', bool(has_path)),
            Item(SHOW, 'Show file location', bool(can_show))]


def labels(entries):
    return [e.label if e else '-' for e in entries]
