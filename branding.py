"""Shared window dressing: one title pattern, one icon, and a Help menu (About, data folder, import, diagnostic log) in every window."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import appdata
import diagnostics
import suite_info

HERE = Path(__file__).resolve().parent
ICON_PNG = HERE / 'assets' / 'app_icon.png'
ICON_ICO = HERE / 'assets' / 'app_icon.ico'
_TRAILING_VERSION = re.compile(r'\s*[|\-]?\s*\bv\d+(\.\d+)*(\s+Beta\s*\d*)?\s*$')


def tidy_title(raw: str) -> str:
    """'WaveSurfer 4104HD | Calibration Verification v56' -> 'Calibration Suite  |  WaveSurfer 4104HD | Calibration Verification  |  v70 Beta 1'.
    Demo windows keep their warning wording; a title already in the suite pattern is left alone."""
    if not raw or raw.startswith(suite_info.NAME):
        return raw
    core = _TRAILING_VERSION.sub('', raw).strip()
    return suite_info.window_title(core)


def apply_icon(root):
    try:
        if sys.platform.startswith('win') and ICON_ICO.exists():
            root.iconbitmap(default=str(ICON_ICO))
        elif ICON_PNG.exists():
            root._cal_icon = tk.PhotoImage(master=root, file=str(ICON_PNG))
            root.iconphoto(True, root._cal_icon)
    except tk.TclError:
        pass


def open_folder(path: Path):
    try:
        if sys.platform.startswith('win'):
            os.startfile(str(path))                        # noqa: S606 - a folder the person asked to open
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(path)])
        else:
            subprocess.Popen(['xdg-open', str(path)])
    except OSError as exc:
        messagebox.showinfo('Open folder', f'{path}\n\n({exc})')


def about(root):
    missing = diagnostics.missing_packages()
    text = (f'{suite_info.NAME}  {suite_info.full_version()}\n\n'
            'Performance-verification procedures for the laboratory\'s instruments.\n\n'
            f'Your data folder:\n{appdata.data_dir()}\n\n'
            f'Python {sys.version.split()[0]}\n')
    if missing:
        text += '\nNot installed: ' + ', '.join(p for _m, p, _u in missing) + '\n'
    if suite_info.EDITION:
        text += f'\nThis is a {suite_info.EDITION} edition for evaluation. It keeps its own data and does not change the released copy.'
    messagebox.showinfo(f'About {suite_info.NAME}', text, parent=root)


def import_data(root):
    folder = filedialog.askdirectory(parent=root, title='Choose the folder of the Calibration Suite copy to import from')
    if not folder:
        return
    src = Path(folder)
    has = [n for n in appdata.DB_NAMES if (src / n).is_file()] or list((src / 'Procedures').glob('*checkpoint*.json')) if src.is_dir() else []
    if not has:
        messagebox.showinfo('Import data', 'No Calibration Suite databases or saved progress were found in that folder.', parent=root)
        return
    if not messagebox.askyesno(
            'Import data',
            f'Copy the databases and saved progress from:\n{src}\n\ninto your data folder:\n{appdata.data_dir()}\n\n'
            'The original folder is not changed. Any file already here is first saved with ".before-import" added to its name.\n\nContinue?',
            parent=root):
        return
    try:
        done = appdata.import_from(src)
    except OSError as exc:
        messagebox.showerror('Import data', f'Could not copy: {exc}', parent=root)
        return
    messagebox.showinfo('Import data', f'Copied {len(done)} file(s). Close and reopen the program to use the imported data.', parent=root)


def save_log(root):
    path = diagnostics.write_log('(requested from the Help menu - no error)', root.title())
    messagebox.showinfo('Diagnostic log', f'Saved for support:\n{path}', parent=root)
    open_folder(path.parent)


def add_help_menu(root):
    try:
        bar = root['menu']
        menubar = root.nametowidget(bar) if bar else tk.Menu(root)
    except tk.TclError:
        menubar = tk.Menu(root)
    help_menu = tk.Menu(menubar, tearoff=False)
    help_menu.add_command(label=f'About {suite_info.NAME}', command=lambda: about(root))
    help_menu.add_separator()
    help_menu.add_command(label='Open my data folder', command=lambda: open_folder(appdata.data_dir()))
    help_menu.add_command(label='Import data from another copy...', command=lambda: import_data(root))
    help_menu.add_command(label='Save diagnostic log for support', command=lambda: save_log(root))
    menubar.add_cascade(label='Help', menu=help_menu)
    root.configure(menu=menubar)


def bind_shortcuts(root):
    """Ctrl+S save progress, Ctrl+O load progress, Ctrl+P export the PDF report, F1 about (the buttons are in the bottom bar)."""
    bar = getattr(root, '_cal_statusbar', None)
    keys = {'Save progress': '<Control-s>', 'Load progress': '<Control-o>', 'Export Report (PDF)': '<Control-p>'}
    for b in getattr(bar, '_buttons', []):
        try:
            seq = keys.get(str(b.cget('text')))
            if seq:
                root.bind(seq, lambda _e, btn=b: (btn.invoke(), 'break')[1])
                b._cal_hint = seq.replace('<Control-', 'Ctrl+').replace('>', '').upper()
        except tk.TclError:
            pass
    root.bind('<F1>', lambda _e: about(root))


def dress(root, where: str = ''):
    """Call once after the window is built (apply_theme does this on idle, so every procedure gets it)."""
    try:
        if not root.winfo_exists():
            return
        root.title(tidy_title(root.title()))
        apply_icon(root)
        diagnostics.install(root, where or root.title())
        add_help_menu(root)
        bind_shortcuts(root)
    except tk.TclError:
        pass
