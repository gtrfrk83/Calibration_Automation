"""The Help menu and the window dressing of every Qt window (Qt twin of branding.py): title pattern, icon, Help menu (About, data folder, import, diagnostic log,
Appearance) and F1 = About.  The diagnostic log (diagnostics.write_log) is plugged into qtui.app's exception dialog.  No Tk import.

    help_menu.dress(window, where='Calibration Procedure Manager')       # call once after the window is built
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow

import appdata
import diagnostics
import suite_info
from qtui import app, theme
from qtui.screens import manager_dialogs as dialogs

HERE = Path(__file__).resolve().parent.parent.parent
ICON_PNG = HERE / 'assets' / 'app_icon.png'
ICON_ICO = HERE / 'assets' / 'app_icon.ico'


def about_text():
    missing = diagnostics.missing_packages()
    text = (f'{suite_info.NAME}  {suite_info.full_version()}\n\n'
            "Performance-verification procedures for the laboratory's instruments.\n\n"
            f'Your data folder:\n{appdata.data_dir()}\n\n'
            f'Python {sys.version.split()[0]}\n')
    if missing:
        text += '\nNot installed: ' + ', '.join(p for _m, p, _u in missing) + '\n'
    if suite_info.EDITION:
        text += f'\nThis is a {suite_info.EDITION} edition for evaluation. It keeps its own data and does not change the released copy.'
    return text


def about(window):
    dialogs.message(window, 'info', f'About {suite_info.NAME}', about_text())


def open_folder(window, path: Path):
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        dialogs.message(window, 'info', 'Open folder', f'{path}\n\n(it could not be opened)')


def import_data(window):
    folder = dialogs.pick_folder(window, 'Choose the folder of the Calibration Suite copy to import from')
    if not folder:
        return
    src = Path(folder)
    has = ([n for n in appdata.DB_NAMES if (src / n).is_file()] or list((src / 'Procedures').glob('*checkpoint*.json'))) if src.is_dir() else []
    if not has:
        dialogs.message(window, 'info', 'Import data', 'No Calibration Suite databases or saved progress were found in that folder.')
        return
    if not dialogs.ask_yes_no(window, 'Import data',
                              f'Copy the databases and saved progress from:\n{src}\n\ninto your data folder:\n{appdata.data_dir()}\n\n'
                              'The original folder is not changed. Any file already here is first saved with ".before-import" added to its name.\n\nContinue?'):
        return
    try:
        done = appdata.import_from(src)
    except OSError as exc:
        dialogs.message(window, 'error', 'Import data', f'Could not copy: {exc}')
        return
    dialogs.message(window, 'info', 'Import data', f'Copied {len(done)} file(s). Close and reopen the program to use the imported data.')


def save_log(window):
    path = diagnostics.write_log('(requested from the Help menu - no error)', window.windowTitle())
    dialogs.message(window, 'info', 'Diagnostic log', f'Saved for support:\n{path}')
    open_folder(window, path.parent)


def add_help_menu(window: QMainWindow):
    """Help is the last menu of the bar.  The actions keep the Tk labels."""
    menu = window.menuBar().addMenu('&Help')
    window.help_actions = {}

    def add(key, text, fn, shortcut=None):
        a = QAction(text, window)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda _c=False: fn())
        menu.addAction(a)
        window.help_actions[key] = a
        return a
    add('about', f'About {suite_info.NAME}', lambda: about(window), 'F1')
    menu.addSeparator()
    add('data', 'Open my data folder', lambda: open_folder(window, appdata.data_dir()))
    add('import', 'Import data from another copy...', lambda: import_data(window))
    add('log', 'Save diagnostic log for support', lambda: save_log(window))
    menu.addSeparator()
    window.appearance_menu = theme.build_appearance_menu(menu)
    if window.appearance_menu is None:                                  # only dark is offered for now: the menu is there, with its one (current) choice
        window.appearance_menu = menu.addMenu('Appearance')
        dark = window.appearance_menu.addAction('Dark  (current)')
        dark.setCheckable(True)
        dark.setChecked(True)
        dark.setEnabled(False)
    window.help_menu = menu
    return menu


def install_hooks():
    """The icon and the diagnostic log of the whole application (before the first window)."""
    app.set_log_hook(lambda text, where: diagnostics.write_log(text, where))
    app.set_icon_hook(lambda: str(ICON_ICO if sys.platform.startswith('win') and ICON_ICO.exists() else ICON_PNG) if (ICON_PNG.exists() or ICON_ICO.exists()) else None)


def dress(window: QMainWindow, where: str = ''):
    window.setWindowTitle(window.windowTitle() if window.windowTitle().startswith(suite_info.NAME) else suite_info.window_title(window.windowTitle()))
    add_help_menu(window)
    return window
