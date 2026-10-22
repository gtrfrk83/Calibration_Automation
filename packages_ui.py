"""The windows of 'Import procedure package...' (the rules are in packages.py; this is only Tk wiring).

    packages_ui.choose_package(parent)          -> path of a .zip, or '' (the picker opens in the library folder when one is set)
    packages_ui.ask_install(parent, preview)    -> True only when the person has read the preview and confirmed
    packages_ui.choose_library_folder(parent)   -> the folder that was set ('' = cleared), or None (cancelled)

The preview shows what the package is and where it came from, every file and whether it is new / replaces an installed file / is identical, whether
the procedure is verified-and-locked now and what the package does about that, and a plain warning that a package is program code.  A package that
was refused shows the reasons and has no Install button.  The 'Install' button stays disabled until the confirmation box is ticked.
"""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import packages
import ui_theme as ui

STATE_TEXT = {'new': 'New', 'replace': 'REPLACES installed file', 'same': 'Identical'}


def choose_package(parent):
    folder = packages.get_library_dir()
    opts = dict(parent=parent, title='Choose a procedure package', filetypes=[('Procedure packages (zip)', '*.zip'), ('All files', '*.*')])
    if folder and Path(folder).is_dir():
        opts['initialdir'] = folder
    return filedialog.askopenfilename(**opts) or ''


def choose_library_folder(parent):
    current = packages.get_library_dir()
    opts = dict(parent=parent, title='Choose the lab\'s procedure library folder (a shared drive, for example)', mustexist=True)
    if current and Path(current).is_dir():
        opts['initialdir'] = current
    chosen = filedialog.askdirectory(**opts)
    if not chosen:
        return None
    packages.set_library_dir(chosen)
    return chosen


def _row(grid, r, label, value, wrap=520, bold=False):
    ttk.Label(grid, text=label, style='Muted.TLabel').grid(row=r, column=0, sticky='nw', pady=2, padx=(0, 12))
    ttk.Label(grid, text=value, wraplength=ui.px(wrap), justify='left', style='Bold.TLabel' if bold else 'TLabel').grid(row=r, column=1, sticky='w', pady=2)


def _origin_text(pv):
    where = {True: 'inside the lab\'s library folder', False: 'NOT inside the lab\'s library folder', None: 'no library folder is set'}[pv.in_library]
    return f'{pv.origin}\n({where})\nsha256 {pv.zip_sha256}'


def _verified_text(pv):
    parts = []
    if pv.installed_version:
        parts.append(f'Installed now: version {pv.installed_version}. Verified on hardware: {pv.status_text}.')
    else:
        parts.append('Not installed yet.')
    if pv.will_unlock:
        parts.append('INSTALLING WILL UNLOCK IT: it is verified and locked now, and this package replaces its files.')
    if pv.mark is not None:
        parts.append('The package carries a verified mark: ' + pv.mark_detail)
    return '\n'.join(parts)


def ask_install(parent, pv):
    """Show the preview; True = the person confirmed the install."""
    win = ui.dialog(parent, 'Import procedure package')
    win.geometry(f'{ui.px(860)}x{ui.px(760)}')
    win.minsize(ui.px(700), ui.px(520))
    result = {'ok': False}
    outer = ttk.Frame(win, padding=(ui.px(20), ui.px(16), ui.px(20), ui.px(14)))
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text='Import procedure package' if pv.ok else 'This package cannot be imported', style='Header.TLabel').pack(anchor='w')
    ttk.Label(outer, text=pv.zip_name, style='Muted.TLabel').pack(anchor='w', pady=(0, 8))

    ui.Notice(outer, packages.CODE_WARNING, 'warn', title='Packages contain program code').pack(fill='x', pady=(0, 6))
    if pv.in_library is not True:
        ui.Notice(outer, 'This file is not inside the lab\'s library folder.' if pv.in_library is False else
                  'No library folder is set (Procedure Development tab), so nothing shows that this file comes from the lab\'s own library.',
                  'bad' if pv.in_library is False else 'info').pack(fill='x', pady=(0, 6))
    if pv.errors:
        ui.Notice(outer, '\n'.join('- ' + e for e in pv.errors[:12]) + ('\n- ... and more' if len(pv.errors) > 12 else ''), 'bad',
                  title='Refused: nothing will be installed').pack(fill='x', pady=(0, 6))
    for w in pv.warnings:
        if w.startswith('This file is NOT') or w.startswith('No library folder'):
            continue
        ui.Notice(outer, w, 'warn', title='Verified on hardware' if 'VERIFIED ON HARDWARE' in w else None).pack(fill='x', pady=(0, 6))

    if pv.proc_id:
        grid = ttk.Frame(outer)
        grid.pack(fill='x', pady=(4, 4))
        _row(grid, 0, 'Procedure', pv.name, bold=True)
        _row(grid, 1, 'Version', pv.version + (f'   (installed: {pv.installed_version})' if pv.installed_version else '   (new procedure)'))
        _row(grid, 2, 'Made by (claimed)', pv.author or 'not stated')
        _row(grid, 3, 'Origin', _origin_text(pv))
        if pv.ok:
            _row(grid, 4, 'Verified status', _verified_text(pv))
            if pv.affected:
                _row(grid, 5, 'Also affected', '; '.join(f'{n}: will show "Changed since verification"' for n, _c in pv.affected))
            if pv.requires:
                _row(grid, 6, 'Needs (already installed)', ', '.join(pv.requires))
    if pv.files:
        ttk.Label(outer, text=f'Files ({len(pv.files)}): replaced files are copied to Backups/packages first', style='Section.TLabel').pack(anchor='w', pady=(8, 4))
        table = ui.make_table(outer, ('path', 'size', 'what'), ('File', 'Size', 'What happens'), (430, 80, 260), anchors={'path': 'w', 'size': 'e', 'what': 'w'},
                              height=8, zebra=True, stretch={'size': False})
        table.tag_configure('replace', foreground=ui.C['warn'])
        for f in pv.files:
            table.insert('', 'end', values=(f.path, f'{f.size:,}', STATE_TEXT[f.state]), tags=(f.state,))

    confirmed = tk.BooleanVar(value=False)
    bar = ttk.Frame(outer)
    bar.pack(side='bottom', fill='x', pady=(12, 0))
    def done(ok):
        result['ok'] = bool(ok)
        win.destroy()
    if pv.ok:
        install = ttk.Button(bar, text='Install package', style='Accent.TButton', state='disabled', command=lambda: done(True))
        install.pack(side='right')
    ttk.Button(bar, text='Cancel' if pv.ok else 'Close', command=lambda: done(False)).pack(side='right', padx=(0, 8))
    if pv.ok:
        def sync(*_):
            install.configure(state='normal' if confirmed.get() else 'disabled')
        confirmed.trace_add('write', sync)
        ttk.Checkbutton(bar, variable=confirmed, text='I know where this package came from and I want to install it.').pack(side='left')
    ui.center_on(win, parent)
    parent.wait_window(win)
    return result['ok'] and pv.ok


def show_result(parent, res, pv):
    lines = [f'Installed {res.name} version {res.version}: {len(res.written)} file(s) written.']
    if res.backups:
        lines.append(f'{len(res.backups)} replaced file(s) were backed up first (Backups/packages/...).')
    if res.unlocked:
        lines.append('The procedure was verified and locked; it is now UNLOCKED and needs hardware re-verification.')
    if res.mark_applied:
        lines.append('The package\'s verified mark matched the installed files, so the procedure is marked verified and locked.')
    elif pv.mark is not None and pv.mark_state != 'valid':
        lines.append('The package\'s verified mark was not accepted: ' + pv.mark_detail)
    lines += res.notes
    messagebox.showinfo('Package installed', '\n\n'.join(lines), parent=parent)
