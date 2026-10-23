"""Calibration Procedure Manager v59. Standard-library launcher and SQLite catalog.

Run: python Calibration_Procedure_Manager.py
Standalone procedures remain runnable independently.

Keep ui_theme.py and mdd_importer_v49.py in the same folder as this file.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import ui_theme as ui
from mdd_importer_v49 import parse_mdd, import_mdd, init_datasheet_db
import appdata
import suite_info
import labregistry
import labregistry_ui
import specmanager_ui
import procmods
import procmods_ui_model
import datasheet_builder_ui
import dsb_manager      # user-built datasheets are listed (not stored) in the Procedures table
import packages          # procedure packages: export / inspect / install a procedure as a zip (packages.py)
import packages_ui
import procscan         # the procedures register themselves: Procedures/<id>.procedure.json (procscan.py)
import verified         # 'Verified on hardware': the Procedures list marks, shows and locks verified procedures
import verified_ui

BASE = Path(__file__).resolve().parent
DB = appdata.db_path('calibration_procedures.sqlite3')     # the person's own data folder (see appdata.py)
BUILTIN = 'Procedures/WaveSurfer_WS4104HD.py'
PROCEDURES = BASE / 'Procedures'
BACKUPS = BASE / 'Backups'
VERSION = suite_info.full_version()
# The procedures are found by scanning Procedures/ for their metadata sidecars (procscan.py); nothing is listed by hand any more.
# STABLE {display name: launcher file} and VERSIONS {launcher file: version} keep their old shape for the code that reads them.
STABLE, VERSIONS = {}, {}


def scan_procedures():
    """The registered procedures in list order, found by scanning Procedures/ (procscan.py).  Also refreshes STABLE and VERSIONS."""
    found = procscan.procs(BASE)
    stable, versions = procscan.legacy_tables(found)
    STABLE.clear(); STABLE.update(stable)
    VERSIONS.clear(); VERSIONS.update(versions)
    return found


ALL_CATEGORIES = 'All categories'
# The Procedures tab has two views (tabs): performance verification and adjustment.  A procedure's view comes from its sidecar `kind`
# or, left out, from its category / name (procscan.classify); user-built datasheets and unknown scripts are verifications.
VIEW_TABS = ((procscan.KIND_VERIFICATION, '  Performance Verification  '), (procscan.KIND_ADJUSTMENT, '  Adjustment  '))
ADJUSTMENT_NOTE = ("Adjustment changes the instrument's calibration. Adjustment procedures are separate from performance verification: "
                   "to check an instrument without changing it, use the Performance Verification tab.")


def find_wavesurfer():
    """Discover the bundled standalone procedure, including later revisions."""
    candidates = list(BASE.glob('WaveSurfer_V*.py'))
    def version(path):
        match = re.search(r'WaveSurfer_V(\d+)', path.name, re.IGNORECASE)
        return int(match.group(1)) if match else -1
    return max(candidates, key=version) if candidates else None


def init_db():
    with sqlite3.connect(DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            script_path TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            serial_number TEXT NOT NULL DEFAULT '',
            interval_months INTEGER,
            procedure_id INTEGER REFERENCES procedures(id) ON DELETE SET NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        init_datasheet_db(conn)
        # Stable paths are relative to this manager, and remain unchanged after updates.
        records = [p.registration for p in scan_procedures()]      # (name, manufacturer, model, category, launcher file) in list order
        for name,mfr,model,category,filename in records:
            stable = str(Path('Procedures') / filename)
            if not (BASE / stable).is_file():
                continue
            # Keep existing procedure IDs and instrument assignments on upgrade.
            matches = conn.execute('SELECT id,script_path FROM procedures WHERE name=? ORDER BY id',(name,)).fetchall()
            if matches:
                chosen = matches[0][0]
                # If another record already uses the stable path, preserve it.
                occupied = conn.execute('SELECT id FROM procedures WHERE script_path=?',(stable,)).fetchone()
                if occupied and occupied[0] != chosen:
                    chosen = occupied[0]
                else:
                    conn.execute('UPDATE procedures SET script_path=?,enabled=1 WHERE id=?',(stable,chosen))
                # Remove duplicates only if no instruments point to them; otherwise retain with disabled status.
                for duplicate_id,_ in matches:
                    if duplicate_id != chosen:
                        conn.execute('UPDATE instruments SET procedure_id=? WHERE procedure_id=?',(chosen,duplicate_id))
                        conn.execute('DELETE FROM procedures WHERE id=?',(duplicate_id,))
            else:
                # Also migrate renamed V54 starter registrations by model/category.
                legacy = None
                if filename == 'Fluke_8846A_Verification.py':
                    legacy = conn.execute("SELECT id FROM procedures WHERE model='8846A' AND category='Digital Multimeter' ORDER BY id LIMIT 1").fetchone()
                if legacy:
                    conn.execute('UPDATE OR IGNORE procedures SET name=?,script_path=?,enabled=1 WHERE id=?',(name,stable,legacy[0]))
                else:
                    conn.execute("INSERT OR IGNORE INTO procedures(name,manufacturer,model,category,script_path,description) VALUES(?,?,?,?,?,?)",(name,mfr,model,category,stable,'Standalone calibration procedure'))


def display_path(path):
    p = Path(path).expanduser().resolve()
    try:
        return str(p.relative_to(BASE))
    except ValueError:
        return str(p)


def script_file(script):
    """Absolute path of a registered script (relative paths are relative to this folder)."""
    path = Path(script)
    if not path.is_absolute():
        path = BASE / path
    return path.resolve()


scan_procedures()


class Manager:
    view_kind = procscan.KIND_VERIFICATION                        # the Procedures view in front (class default; __init__ and the tabs set it)
    _empty_lib_default = 'No procedures match.\nUse "Register procedure..." to add one.'
    def __init__(self, root):
        self.root = root
        ui.apply_theme(root)
        root.title('Calibration Procedure Manager')
        ui.fit_window(root, 1260, 800, min_w=1000, min_h=580)
        self.demo = tk.BooleanVar(value=False)
        self.fast_demo = tk.BooleanVar(value=False)       # demo without windows or commands (the old quick demo)
        self.status = tk.StringVar(value='Select a procedure, then press Run Procedure.')
        self.search = tk.StringVar()
        self.category = tk.StringVar(value=ALL_CATEGORIES)

        banner = ui.Banner(root, 'Calibration Procedure Manager', 'Run, document and maintain your calibration procedures')
        banner.pack(fill='x')
        banner.add_pill('Database: ' + DB.name, 'info')
        ui.StatusBar(root, self.status, right=VERSION).pack(side='bottom', fill='x')

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True)
        ui.TabStrip(self.notebook)
        self.library_frame = ttk.Frame(self.notebook, padding=16)
        self.instruments_frame = ttk.Frame(self.notebook, padding=16)
        self.history_frame = ttk.Frame(self.notebook, padding=16)
        self.specs_frame = ttk.Frame(self.notebook, padding=16)
        self.datasheets_frame = ttk.Frame(self.notebook, padding=16)
        self.dsb_frame = ttk.Frame(self.notebook, padding=16)
        self.development_frame = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(self.library_frame, text='  Procedures  ')
        self.notebook.add(self.instruments_frame, text='  Instruments  ')
        self.notebook.add(self.history_frame, text='  Asset History  ')
        self.notebook.add(self.specs_frame, text='  Standards Specs  ')
        self.notebook.add(self.datasheets_frame, text='  Mudcats Datasheet Importer  ')
        self.notebook.add(self.dsb_frame, text='  Datasheet Builder  ')
        self.notebook.add(self.development_frame, text='  Procedure Development  ')
        self.build_library_tab()
        self.build_development_tab()
        self.build_datasheets_tab()
        self.build_datasheet_builder_tab()
        self.build_instruments_tab()
        self.history_panel = labregistry_ui.HistoryPanel(self.history_frame)
        self.history_panel.pack(fill='both', expand=True)
        self.specs_panel = specmanager_ui.SpecManagerPanel(self.specs_frame)
        self.specs_panel.pack(fill='both', expand=True)
        ui.polish(root)
        self.notebook.bind('<<NotebookTabChanged>>', self._tab_changed)
        self.refresh()
        self.refresh_instruments()
        self.refresh_development()
        root.bind('<Control-f>', lambda _e: (self.notebook.select(self.library_frame), self.search_entry.focus_set()))

    # (design width, narrowest width) of the Procedures table columns, in 96-dpi pixels
    TABLE_COLUMNS = {'name': (235, 110), 'manufacturer': (90, 60), 'model': (80, 60), 'category': (175, 90), 'ready': (80, 64), 'verified': (200, 100)}

    def _fit_table_columns(self, avail):
        """Give the Procedures table columns the width of the table: design widths when it fits (the spare goes to the name), otherwise every column
        shrinks towards its narrowest width in proportion to how much it has to give, so no column (Verified on hardware) is cut off."""
        if avail < 60:
            return
        want = {c: ui.px(w) for c, (w, _n) in self.TABLE_COLUMNS.items()}
        least = {c: ui.px(n) for c, (_w, n) in self.TABLE_COLUMNS.items()}
        over = sum(want.values()) - avail
        if over > 0:
            give = {c: want[c] - least[c] for c in want}
            total = sum(give.values())
            for c in want:
                want[c] -= over * give[c] / total if total else 0
        else:
            want['name'] -= over
        for c, w in want.items():
            self.table.column(c, width=int(w))

    def _tab_changed(self, _event=None):
        tab = self.notebook.nametowidget(self.notebook.select())
        if tab is self.library_frame:
            self.refresh_details()
            self.status.set('Select a procedure, then press Run procedure (or Try in demo mode).')
        elif tab is self.instruments_frame:
            self.refresh_instruments()
            self.status.set('Register the instruments you calibrate, assign a procedure, and launch it from here.')
        elif tab is self.history_frame:
            self.history_panel.refresh()
            self.status.set('Every exported PDF report is recorded here. Double-click a test point to see its drift across reports.')
        elif tab is self.specs_frame:
            self.specs_panel.refresh()
            self.status.set('Published specifications of the calibrators used as standards; they set the lowest uncertainty that may be reported.')
        elif tab is self.datasheets_frame:
            self.status.set('Import Cal Processor .MDD datasheets as read-only templates.')
        elif tab is self.dsb_frame:
            self.dsb_panel.refresh()
            self.status.set('Build your own datasheet from a manufacturer specification; each save is a new version and a runnable procedure.')
        else:
            self.refresh_development()
            self.status.set('Maintainer tools: test, update and roll back procedure scripts.')

    # ------------------------------------------------------------------ small helpers
    def _empty_state(self, table, text):
        label = ttk.Label(table.master, text=text, style='Muted.TLabel', justify='center')
        table._empty = label
        return label

    @staticmethod
    def _toggle_empty(table, empty):
        if empty:
            table._empty.place(relx=0.5, rely=0.45, anchor='center')
            table._empty.lift()
        else:
            table._empty.place_forget()

    # ------------------------------------------------------------------ Procedures tab
    def build_library_tab(self):
        outer = self.library_frame
        # two views of the same list: the notebook only carries the tab strip (its pages are empty); the table and the card below are shared
        self.view_nb = ttk.Notebook(outer, height=1)
        self.view_pages = {}
        for kind, text in VIEW_TABS:
            page = ttk.Frame(self.view_nb)
            self.view_pages[kind] = page
            self.view_nb.add(page, text=text)
        self.view_nb.pack(fill='x')
        ui.TabStrip(self.view_nb)
        self.view_nb.bind('<<NotebookTabChanged>>', self._view_changed)
        self.adjust_note = ui.Notice(outer, text=ADJUSTMENT_NOTE, kind='warn')
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(8, 8))
        ttk.Label(bar, text='Find').pack(side='left')
        self.search_entry = ttk.Entry(bar, textvariable=self.search, width=30)
        self.search_entry.pack(side='left', padx=(8, 12))
        self.search.trace_add('write', lambda *_: self.refresh())
        self.category_box = ttk.Combobox(bar, textvariable=self.category, width=26, state='readonly', values=[ALL_CATEGORIES])
        self.category_box.pack(side='left')
        self.category_box.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
        ttk.Button(bar, text='Clear', style='Quiet.TButton', command=lambda: (self.search.set(''), self.category.set(ALL_CATEGORIES))).pack(side='left', padx=6)
        ttk.Button(bar, text='Remove from library', command=self.remove).pack(side='right')
        ttk.Button(bar, text='Register procedure...', command=self.add).pack(side='right', padx=8)
        ttk.Button(bar, text='Import procedure package...', command=self.import_package).pack(side='right')

        split = ttk.Frame(outer)
        split.pack(fill='both', expand=True)
        split.columnconfigure(0, weight=1)
        split.rowconfigure(0, weight=1)
        cols = ('name', 'manufacturer', 'model', 'category', 'ready', 'verified')
        self.table = ui.make_table(split, cols, ('Procedure', 'Manufacturer', 'Model', 'Category', 'Status', 'Verified on hardware'),
                                   (235, 90, 80, 175, 80, 200), anchors={'name': 'w', 'manufacturer': 'w', 'model': 'w', 'category': 'w', 'verified': 'w'},
                                   zebra=True, pack=False, stretch={'manufacturer': False, 'model': False, 'category': False, 'ready': False, 'verified': False})
        self.table.master.grid(row=0, column=0, sticky='nsew')
        self.table.bind('<Configure>', lambda e: self._fit_table_columns(e.width), add='+')     # on a narrow window the columns give way instead of being clipped
        self.table.tag_configure('missing', foreground=ui.C['bad'])
        self.table.tag_configure('modified', foreground=ui.C['warn'])
        self.table.tag_configure('verified', foreground=ui.C['good'])
        self.empty_lib = self._empty_state(self.table, 'No procedures match.\nUse "Register procedure..." to add one.')
        self.table.bind('<Double-1>', lambda _: self.run_selected())
        self.table.bind('<<TreeviewSelect>>', lambda _: (self.refresh_details(), self.refresh_development()))
        self.table.bind('<Return>', lambda _: self.run_selected())

        card = ttk.LabelFrame(split, text='Selected procedure', padding=16)
        card.grid(row=0, column=1, sticky='nsew', padx=(14, 0))
        card.configure(width=ui.px(340))
        self.d_name = tk.StringVar(); self.d_sub = tk.StringVar(); self.d_desc = tk.StringVar(); self.d_path = tk.StringVar()
        ttk.Label(card, textvariable=self.d_name, style='Section.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w')
        ttk.Label(card, textvariable=self.d_sub, style='Muted.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w', pady=(2, 8))
        self.d_pill = ui.Pill(card, '', 'neutral')
        self.d_pill.pack(anchor='w')
        self.d_ver = ui.Pill(card, '', 'neutral')                  # 'VERIFIED ON HARDWARE <date> - LOCKED' / 'CHANGED SINCE' / 'UNLOCKED' / 'NOT VERIFIED'
        self.d_ver.pack(anchor='w', pady=(6, 0))
        self.d_ver_text = tk.StringVar()
        ttk.Label(card, textvariable=self.d_ver_text, style='Small.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w', pady=(4, 0))
        ttk.Label(card, textvariable=self.d_desc, wraplength=ui.px(300), justify='left').pack(anchor='w', pady=(10, 4))
        ttk.Label(card, textvariable=self.d_path, style='Small.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w')
        self.btn_run = ttk.Button(card, text='▶  Run procedure', style='Accent.TButton', command=self.run_selected)
        self.btn_run.pack(fill='x', pady=(18, 6))
        self.btn_demo = ttk.Button(card, text='Try in demo mode (virtual instruments)', command=lambda: self.run_selected(demo=True))
        self.btn_demo.pack(fill='x')
        ttk.Checkbutton(card, text='Fast demo (no windows)', variable=self.fast_demo).pack(anchor='w', pady=(4, 0))
        self.d_mod = ui.Pill(card, '', 'warn')                    # 'MODIFIED (n)': saved model-wide procedure changes exist
        self.btn_verify = ttk.Button(card, text='Mark verified on hardware...', command=self.mark_verified)
        self.btn_verify.pack(fill='x', pady=(6, 0))
        self.btn_lock = ttk.Button(card, text='Unlock for editing...', command=self.toggle_lock)
        self.btn_lock.pack(fill='x', pady=(6, 0))
        ttk.Label(card, text='Run procedure uses real instruments. Demo mode connects VIRTUAL instruments: the windows of a real run appear and commands go to simulated instruments, so you can rehearse safely. Nothing from a demo is calibration evidence.',
                  style='Small.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w', pady=(10, 0))

    def _view_changed(self, _event=None):
        kind = next((k for k, page in self.view_pages.items() if str(page) == self.view_nb.select()), procscan.KIND_VERIFICATION)
        if kind == self.view_kind:
            return
        self.view_kind = kind
        self.category.set(ALL_CATEGORIES)                       # the category list belongs to the view
        if kind == procscan.KIND_ADJUSTMENT:
            self.adjust_note.pack(fill='x', pady=(8, 0), after=self.view_nb)
        else:
            self.adjust_note.pack_forget()
        self.refresh()

    def _kind_of(self, id_, name, category, script):
        """'verification' | 'adjustment' of a list row: the sidecar's kind (or its category / name default) for a scanned procedure, the same text rule for any other."""
        if dsb_manager.is_user_iid(id_) or not script:
            return procscan.KIND_VERIFICATION
        proc = self._scanned.get(Path(str(script)).name.casefold())
        if proc is not None:
            return proc.effective_kind
        return procscan.classify(name, category)

    def refresh_details(self):
        rec = self._selected_row()
        if not rec:
            self.d_name.set('No procedure selected')
            self.d_sub.set('Pick one from the list.')
            self.d_desc.set(''); self.d_path.set('')
            self.d_pill.set('', 'neutral')
            self.btn_run.configure(state='disabled'); self.btn_demo.configure(state='disabled')
            self.d_mod.pack_forget()
            self.d_ver.set('', 'neutral'); self.d_ver_text.set('')
            self.btn_verify.configure(state='disabled'); self.btn_lock.configure(state='disabled')
            return
        id_, name, mfr, model, cat, script, desc = rec
        user = self._user_rows().get(str(id_))
        found = script_file(script).is_file() and (user is None or Path(user['spec_path']).is_file())
        version = VERSIONS.get(Path(script).name)
        self.d_name.set(name)
        self.d_sub.set('  |  '.join(x for x in (f'{mfr} {model}'.strip(), cat) if x))
        self.d_desc.set(desc or '')
        self.d_path.set(f'File: {script}' + (f'   (version {version})' if version else '') if user is None else
                        f'User-built datasheet v{user["version"]}   |   spec: {user["spec_path"]}')
        self.d_pill.set('Ready to run' if found else 'Script file not found', 'good' if found else 'bad')
        state = 'normal' if found else 'disabled'
        self.btn_run.configure(state=state); self.btn_demo.configure(state=state)
        n = self._mod_counts().get((model or '').casefold(), 0)
        if n:
            self.d_mod.set(procmods_ui_model.chip_text(n), 'warn')
            self.d_mod.pack(anchor='w', pady=(6, 0), before=self.btn_run)
        else:
            self.d_mod.pack_forget()
        self.show_verified(rec)

    # ------------------------------------------------------------------ Verified on hardware (verified.py)
    def _verified(self):
        if getattr(self, 'verified', None) is None:
            self.verified = verified.Registry()
        return self.verified

    def _ver_entry(self, rec):
        """The verified.Entry of a list row (id, name, manufacturer, model, category, script, ...)."""
        id_, name, _mfr, model, _cat, script = rec[:6]
        user = self._user_rows().get(str(id_))
        return verified.make_entry(name, model, script, BASE, user_uid=user['uid'] if user else None, spec_path=user['spec_path'] if user else '')

    def _ver_status(self, rec):
        """(entry, Status) read afresh from the registry: another window may have unlocked it since the list was drawn."""
        entry = self._ver_entry(rec)
        return entry, self._verified().status(entry)

    def show_verified(self, rec):
        """The selected procedure's verification pill, notes and the two buttons."""
        entry, status = self._ver_status(rec)
        self.d_ver.set(status.pill, status.tone)
        self.d_ver_text.set('\n'.join(status.detail_lines()))
        state = verified.ui_state(status)
        for button, key in ((self.btn_verify, 'verify'), (self.btn_lock, 'lock')):
            text, enabled = state[key]
            button.configure(text=text, state='normal' if enabled else 'disabled')
        return status

    def mark_verified(self):
        rec = self._selected_row()
        if not rec:
            return None
        entry, status = self._ver_status(rec)
        form = verified_ui.ask_mark(self.root, entry, status)
        if not form:
            return None
        try:
            record = self._verified().verify(entry, form['who'], form['on_date'], form['note'], form['hardware'])
        except verified.VerifyError as ex:
            messagebox.showerror('Not recorded', str(ex), parent=self.root)
            return None
        self.refresh()
        self.status.set(f'"{entry.name}" is marked verified on hardware ({record.verified_on}) and locked against edits.')
        return record

    def toggle_lock(self):
        """'Unlock for editing...' (a typed reason is required) or, once unlocked and unchanged, 'Lock again'."""
        rec = self._selected_row()
        if not rec:
            return None
        entry, status = self._ver_status(rec)
        try:
            if status.kind == 'unlocked':
                who = simpledialog.askstring('Lock again', 'Nothing has changed since it was verified. Your name (recorded):',
                                             initialvalue=ui.Settings('verified').get('who', '') or verified.default_who(), parent=self.root)
                if not who:
                    return None
                record = self._verified().relock(entry, who)
                message = f'"{entry.name}" is locked again.'
            elif status.kind in ('verified', 'changed'):
                form = verified_ui.ask_unlock(self.root, entry, status)
                if not form:
                    return None
                record = self._verified().unlock(entry.proc_key, form['who'], form['reason'])
                message = f'"{entry.name}" is unlocked for editing; the reason is recorded.'
            else:
                return None
        except verified.VerifyError as ex:
            messagebox.showerror('Not changed', str(ex), parent=self.root)
            return None
        self.refresh()
        self.status.set(message)
        return record

    def _user_rows(self):
        """{iid: user-built row} of the last refresh (dsb_manager.user_rows)."""
        return getattr(self, '_user', None) or {}

    def _selected_row(self):
        sel = self.table.selection()
        if not sel:
            return None
        if dsb_manager.is_user_iid(sel[0]):
            u = self._user_rows().get(sel[0])
            return (u['iid'], u['name'], u['manufacturer'], u['model'], u['category'], u['script'], u['description']) if u else None
        with sqlite3.connect(DB) as conn:
            return conn.execute('SELECT id,name,manufacturer,model,category,script_path,description FROM procedures WHERE id=?', (int(sel[0]),)).fetchone()

    def refresh(self):
        init_db()
        with sqlite3.connect(DB) as conn:
            rows = conn.execute('SELECT id,name,manufacturer,model,category,script_path FROM procedures WHERE enabled=1 ORDER BY manufacturer,model,name').fetchall()
        self._user = {r['iid']: r for r in dsb_manager.user_rows()}          # user-built datasheets: listed after the library rows, never written to the database
        rows = rows + [(r['iid'], r['name'], r['manufacturer'], r['model'], r['category'], r['script']) for r in self._user.values()]
        self._scanned = {p.launcher_name.casefold(): p for p in procscan.procs(BASE)}
        kinds = {r[0]: self._kind_of(r[0], r[1], r[4], r[5]) for r in rows}
        in_view = [r for r in rows if kinds[r[0]] == self.view_kind]
        cats = sorted({r[4] for r in in_view if r[4]})
        self.category_box['values'] = [ALL_CATEGORIES] + cats
        if self.category.get() != ALL_CATEGORIES and self.category.get() not in cats:
            self.category.set(ALL_CATEGORIES)
        term = self.search.get().strip().lower()
        cat = self.category.get()
        keep = self.table.selection()
        self.table.delete(*self.table.get_children())
        shown = 0
        mods = self._mod_counts(refresh=True)
        match = lambda r: not (cat != ALL_CATEGORIES and r[4] != cat) and not (term and term not in ' '.join((r[1], r[2], r[3], r[4])).lower())  # noqa: E731
        listed = [r for r in in_view if match(r)]
        elsewhere = sum(1 for r in rows if kinds[r[0]] != self.view_kind and match(r)) if term else 0
        entries = [self._ver_entry(r) for r in listed]
        self._ver_cache = self._verified().statuses(entries)          # one registry read; fingerprints only for verified procedures
        for (id_, name, mfr, model, category, script), entry in zip(listed, entries):
            found = script_file(script).is_file()
            n_mod = mods.get((model or '').casefold(), 0)
            vstat = self._ver_cache.get(entry.proc_key)
            tags = ['even' if shown % 2 == 0 else 'odd'] + ([] if found else ['missing']) + (['modified'] if n_mod else []) + \
                   (['verified'] if vstat is not None and vstat.kind == 'verified' and found and not n_mod else [])
            status = ('Ready' if found else 'Missing') + (f'  [{dsb_manager.TAG}]' if dsb_manager.is_user_iid(id_) else '') + \
                     (f'  {procmods_ui_model.chip_text(n_mod)}' if n_mod else '')
            self.table.insert('', 'end', iid=str(id_), values=(name, mfr, model, category, status, vstat.text if vstat is not None else 'Not verified'), tags=tags)
            shown += 1
        text = self._empty_lib_default
        if shown == 0 and elsewhere:
            other = 'Adjustment' if self.view_kind == procscan.KIND_VERIFICATION else 'Performance Verification'
            text = f'No procedures match in this tab.\n{elsewhere} match in the {other} tab.'
        self.table._empty.configure(text=text)                  # the label _toggle_empty shows
        self._toggle_empty(self.table, shown == 0)
        if keep and self.table.exists(keep[0]):
            self.table.selection_set(keep[0])
        elif shown:
            self.table.selection_set(self.table.get_children()[0])
        self.refresh_details()
        self.status.set(f'{shown} of {len(in_view)} procedure(s) shown. Double-click a procedure to run it.')

    def _mod_counts(self, refresh=False):
        """{model: n} of saved model-wide procedure changes (one query per list refresh; never blocks the list if the registry is unreadable)."""
        if refresh or not hasattr(self, '_mods'):
            try:
                self._mods = procmods_ui_model.model_counts(procmods.Store())
            except Exception:
                self._mods = {}
        return self._mods

    def selected(self):
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo('Select a procedure', 'Select a procedure from the list first.')
            return None
        with sqlite3.connect(DB) as conn:
            return conn.execute('SELECT name,script_path FROM procedures WHERE id=? AND enabled=1', (int(selection[0]),)).fetchone()

    def _launch(self, name, script, demo, asset=None, extra=None):
        path = script_file(script)
        if not path.is_file():
            messagebox.showerror('Procedure not found', f'Cannot locate the procedure script:\n{path}\n\nRegister its new location if it was moved.')
            return False
        args = [sys.executable, str(path)]
        if demo:
            args.append('--demo')
            if self.fast_demo.get():
                args.append('--fast-demo')
        if asset:
            args += ['--asset', asset]
        args += list(extra or [])
        try:
            subprocess.Popen(args, cwd=str(path.parent))
        except OSError as exc:
            messagebox.showerror('Launch failed', str(exc))
            return False
        return True

    def run_selected(self, demo=None):
        sel = self.table.selection()
        if sel and dsb_manager.is_user_iid(sel[0]):               # a user-built datasheet: the generic launcher with its spec file
            u = self._user_rows().get(sel[0])
            demo = self.demo.get() if demo is None else demo
            if u and self._launch(u['name'], u['script'], demo, extra=['--spec', u['spec_path']]):
                self.status.set(f'Launched {u["name"]}' + (' in demo mode.' if demo else '.'))
            return
        selected = self.selected()
        if not selected:
            return
        name, script = selected
        demo = self.demo.get() if demo is None else demo
        if self._launch(name, script, demo):
            self.status.set(f'Launched {name}' + (' in demo mode.' if demo else '.'))

    def add(self):
        script = filedialog.askopenfilename(title='Select a standalone Python calibration procedure',
                                            filetypes=[('Python scripts', '*.py')])
        if not script:
            return
        path = display_path(script)
        win = ui.dialog(self.root, 'Register Calibration Procedure')
        win.resizable(False, False)
        fields = [('Procedure name *', Path(script).stem.replace('_', ' ')),
                  ('Manufacturer', ''), ('Model', ''), ('Category', ''), ('Description', '')]
        variables = {}
        frame = ttk.Frame(win, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Register a procedure', style='Header.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(frame, text=f'Script: {path}', style='Small.TLabel').grid(row=1, column=0, columnspan=2, sticky='w', pady=(2, 12))
        for index, (label, default) in enumerate(fields, 2):
            ttk.Label(frame, text=label).grid(row=index, column=0, sticky='w', pady=5, padx=(0, 14))
            var = tk.StringVar(value=default)
            ttk.Entry(frame, textvariable=var, width=48).grid(row=index, column=1, pady=5)
            variables[label.rstrip(' *')] = var
        def save():
            name = variables['Procedure name'].get().strip()
            if not name:
                messagebox.showerror('Missing name', 'Enter a procedure name.', parent=win)
                return
            try:
                with sqlite3.connect(DB) as conn:
                    conn.execute('''INSERT INTO procedures (name,manufacturer,model,category,script_path,description)
                                    VALUES (?,?,?,?,?,?)''',
                                 (name, variables['Manufacturer'].get().strip(), variables['Model'].get().strip(),
                                  variables['Category'].get().strip(), path, variables['Description'].get().strip()))
            except sqlite3.IntegrityError:
                messagebox.showerror('Already registered', 'This script is already in the library.', parent=win)
                return
            win.destroy()
            self.refresh()
            self.status.set(f'Registered "{name}".')
        buttons = ttk.Frame(frame)
        buttons.grid(row=len(fields) + 2, column=0, columnspan=2, sticky='e', pady=(16, 0))
        ttk.Button(buttons, text='Cancel', command=win.destroy).pack(side='right')
        ttk.Button(buttons, text='Save procedure', style='Accent.TButton', command=save).pack(side='right', padx=8)
        win.bind('<Return>', lambda _: save())
        ui.center_on(win, self.root)

    def remove(self):
        sel = self.table.selection()
        if sel and dsb_manager.is_user_iid(sel[0]):
            messagebox.showinfo('User-built datasheet', 'A user-built datasheet is not part of the library file. Delete it in the Datasheet Builder.')
            return
        rec = self._selected_row()
        if rec:
            entry, status = self._ver_status(rec)
            if status.locked:                                      # verified on hardware and locked: it stays in the list until it is unlocked
                messagebox.showinfo('Verified and locked', verified.lock_text(status.record), parent=self.root)
                return
        selected = self.selected()
        if not selected:
            return
        name, _ = selected
        if not messagebox.askyesno('Remove from library',
                                   f'Remove "{name}" from the procedure library?\n\nThe Python script will not be deleted.'):
            return
        with sqlite3.connect(DB) as conn:
            conn.execute('DELETE FROM procedures WHERE id=?', (int(self.table.selection()[0]),))
        self.refresh()
        self.status.set(f'Removed "{name}" from the library (script file kept).')

    # ------------------------------------------------------------------ Procedure development tab
    def build_development_tab(self):
        frame = self.development_frame
        ui.Notice(frame, 'For maintainers. Installing an update replaces the procedure script after saving a backup. '
                         'Syntax checking does not prove an instrument procedure is safe - install trusted code only. '
                         'Databases, checkpoints and reports are never overwritten.', 'warn', title='Handle with care').pack(fill='x')
        self.dev_info = tk.StringVar(value='Select a procedure on the Procedures tab.')
        box = ttk.LabelFrame(frame, text='Selected procedure', padding=14)
        box.pack(fill='x', pady=(14, 10))
        ttk.Label(box, textvariable=self.dev_info, wraplength=900, justify='left').pack(anchor='w', fill='x')
        bar = ttk.Frame(box)
        bar.pack(fill='x', pady=(12, 0))
        ttk.Button(bar, text='Test in demo mode', command=self.test_demo).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Install update (.py)...', style='Accent.TButton', command=self.install_update).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Restore previous version...', command=self.restore_previous).pack(side='left')
        lib = ttk.LabelFrame(frame, text='Procedure packages', padding=14)
        lib.pack(fill='x', pady=(0, 10))
        self.lib_folder = tk.StringVar()
        ttk.Label(lib, text='Library folder (where the lab keeps its procedure packages; the "Import procedure package..." picker opens here):',
                  style='Muted.TLabel', wraplength=900, justify='left').pack(anchor='w')
        row = ttk.Frame(lib)
        row.pack(fill='x', pady=(6, 0))
        ttk.Label(row, textvariable=self.lib_folder, wraplength=620, justify='left').pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Clear', command=lambda: self.set_library_folder('')).pack(side='right')
        ttk.Button(row, text='Choose folder...', command=self.choose_library_folder).pack(side='right', padx=(0, 8))
        self._show_library_folder()
        ttk.Label(frame, text='Saved backups of this procedure', style='Section.TLabel').pack(anchor='w', pady=(6, 6))
        self.backup_table = ui.make_table(frame, ('file', 'when'), ('Backup file', 'Saved'), (560, 200), anchors={'file': 'w', 'when': 'w'}, height=6, zebra=True)
        self.backup_empty = self._empty_state(self.backup_table, 'No backups yet - one is created automatically\nthe first time you install an update.')

    # ------------------------------------------------------------------ procedure packages (packages.py)
    def _show_library_folder(self):
        folder = packages.get_library_dir()
        self.lib_folder.set(folder if folder else '(not set: the picker opens in the folder you used last)')

    def set_library_folder(self, folder):
        try:
            packages.set_library_dir(folder)
        except OSError as exc:
            messagebox.showerror('Library folder', f'The setting could not be saved ({exc}).', parent=self.root)
        self._show_library_folder()

    def choose_library_folder(self):
        chosen = packages_ui.choose_library_folder(self.root)
        if chosen is not None:
            self._show_library_folder()

    def import_package(self):
        """Pick a package, show what it is and what it would do, and install it only after the person confirms."""
        path = packages_ui.choose_package(self.root)
        if not path:
            return
        reg, library = self._verified(), packages.get_library_dir()
        preview = packages.inspect(path, BASE, reg, library)
        if not packages_ui.ask_install(self.root, preview):
            self.status.set('Package not imported.')
            return
        try:
            result = packages.install(path, BASE, reg, expected_sha256=preview.zip_sha256, library_dir=library)
        except packages.PackageError as exc:
            messagebox.showerror('Import failed', str(exc), parent=self.root)
            return
        self.refresh()                                       # the scan finds a new procedure; a verified one that changed shows its state
        self.refresh_development()
        self.status.set(f'Imported {result.name} version {result.version} ({len(result.written)} file(s) written).')
        packages_ui.show_result(self.root, result, preview)

    def _selected_record(self):
        sel = self.table.selection()
        if not sel or dsb_manager.is_user_iid(sel[0]):
            return None
        with sqlite3.connect(DB) as conn:
            return conn.execute('SELECT id,name,script_path FROM procedures WHERE id=?', (int(sel[0]),)).fetchone()

    def _managed_path(self, record):
        if not record:
            return None
        p = Path(record[2])
        if p.is_absolute():
            return None
        path = (BASE / p).resolve()
        # Restrict replacement to the managed Procedures directory.
        try:
            path.relative_to(PROCEDURES.resolve())
        except ValueError:
            return None
        return path if path.suffix.lower() == '.py' else None

    def refresh_development(self):
        if not hasattr(self, 'dev_info'):
            return
        self.backup_table.delete(*self.backup_table.get_children())
        rec = self._selected_record()
        if not rec:
            self.dev_info.set('Select a procedure on the Procedures tab first.')
            self._toggle_empty(self.backup_table, True)
            return
        path = self._managed_path(rec)
        if not path:
            self.dev_info.set(f'{rec[1]} - external or unmanaged script; register or copy it under Procedures before using updates.')
            self._toggle_empty(self.backup_table, True)
            return
        version = VERSIONS.get(path.name, 'custom')
        backups = self._available_backups(rec)
        self.dev_info.set(f'{rec[1]}\n{path.relative_to(BASE)}   |   bundled baseline v{version}   |   {len(backups)} backup(s)')
        for b in backups:
            when = datetime.datetime.fromtimestamp(b.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            self.backup_table.insert('', 'end', values=(b.name, when))
        self._toggle_empty(self.backup_table, not backups)

    def test_demo(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showinfo('Select a procedure', 'Select a procedure in the Procedures tab first.')
            return
        if self._launch(rec[1], rec[2], True):
            self.status.set(f'Demo launched: {rec[1]}')

    def _validated_update(self, source):
        if not source.is_file() or source.suffix.lower() != '.py':
            raise ValueError('Select a Python .py file.')
        if source.stat().st_size > 10_000_000:
            raise ValueError('Procedure file exceeds 10 MB.')
        raw = source.read_bytes()
        if b'\x00' in raw:
            raise ValueError('File contains binary data.')
        # Parse and compile WITHOUT executing the submitted procedure.
        text = raw.decode('utf-8-sig')
        compile(text, str(source), 'exec')
        return raw

    def _backup(self, rec, path):
        folder = BACKUPS / str(rec[0]); folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup = folder / f'{stamp}_{path.stem}.py'
        shutil.copy2(path, backup)
        return backup

    def _atomic_replace(self, raw, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.update_', suffix='.py', dir=str(target.parent))
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def install_update(self):
        rec = self._selected_record()
        path = self._managed_path(rec)
        if not path or not path.is_file():
            messagebox.showerror('Not managed', 'Select a procedure whose script is in the Procedures folder.'); return
        chosen = filedialog.askopenfilename(parent=self.root, title=f'Choose updated script for {rec[1]}', filetypes=[('Python scripts', '*.py')])
        if not chosen:
            return
        source = Path(chosen).resolve()
        if source == path:
            messagebox.showerror('Same file', 'Choose the downloaded update file, not the installed procedure.'); return
        try:
            raw = self._validated_update(source)
        except Exception as exc:
            messagebox.showerror('Update rejected', str(exc)); return
        old_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        new_digest = hashlib.sha256(raw).hexdigest()
        if old_digest == new_digest:
            messagebox.showinfo('Already installed', 'The selected file is identical to the installed procedure.'); return
        if not messagebox.askyesno('Confirm procedure update', f'Update: {rec[1]}\n\nFrom: {source.name}\nTo: {path.relative_to(BASE)}\n\nA backup will be created first.\n\nInstall only trusted procedure code; syntax validation does not prove instrument safety.'):
            return
        try:
            backup = self._backup(rec, path)
            self._atomic_replace(raw, path)
        except Exception as exc:
            messagebox.showerror('Update failed', f'{exc}\n\nCheck the backup before continuing.'); return
        self.refresh_development()
        self.refresh()                                                   # a verified procedure now is unlocked and shows 'Changed since verification'
        self.status.set(f'Updated {rec[1]}; backup saved as {backup.name}. Restart any open procedure windows to use it.')
        messagebox.showinfo('Update installed', f'Updated {rec[1]}.\nBackup: {backup}\n\nClose and reopen any running procedure windows.')

    def _available_backups(self, rec):
        folder = BACKUPS / str(rec[0])
        return sorted(folder.glob('*.py'), reverse=True) if folder.exists() else []

    def view_backups(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showinfo('Select procedure', 'Select a procedure first.'); return
        backups = self._available_backups(rec)
        messagebox.showinfo('Procedure backups', '\n'.join(p.name for p in backups[:25]) if backups else 'No backups yet.')

    def restore_previous(self):
        rec = self._selected_record(); path = self._managed_path(rec)
        if not path or not path.is_file():
            messagebox.showerror('Not managed', 'Select a managed procedure.'); return
        backups = self._available_backups(rec)
        if not backups:
            messagebox.showinfo('No backups', 'No previous versions are available.'); return
        win = ui.dialog(self.root, 'Restore procedure version'); win.geometry(f'{ui.px(680)}x{ui.px(420)}')
        ttk.Label(win, text=f'Restore {rec[1]}', style='Header.TLabel').pack(anchor='w', padx=16, pady=(16, 4))
        ttk.Label(win, text='Pick the version to bring back. The current version is backed up first.', style='Muted.TLabel').pack(anchor='w', padx=16, pady=(0, 10))
        lb = tk.Listbox(win, exportselection=False, borderwidth=1, relief='solid', highlightthickness=0, selectbackground=ui.C['select'], selectforeground=ui.C['text'], activestyle='none')
        lb.pack(fill='both', expand=True, padx=16)
        for b in backups:
            lb.insert('end', b.name)
        lb.selection_set(0)
        def restore():
            sel = lb.curselection()
            if not sel:
                return
            source = backups[sel[0]]
            try:
                raw = self._validated_update(source)
            except Exception as exc:
                messagebox.showerror('Invalid backup', str(exc), parent=win); return
            if not messagebox.askyesno('Confirm restore', f'Restore {source.name}?\nThe current procedure will also be backed up.', parent=win):
                return
            try:
                self._backup(rec, path); self._atomic_replace(raw, path)
            except Exception as exc:
                messagebox.showerror('Restore failed', str(exc), parent=win); return
            win.destroy(); self.refresh_development(); self.refresh(); self.status.set(f'Restored {rec[1]} from {source.name}')
            messagebox.showinfo('Restored', 'Previous procedure restored. Reopen any running procedure windows.')
        row = ttk.Frame(win); row.pack(fill='x', padx=16, pady=14)
        ttk.Button(row, text='Cancel', command=win.destroy).pack(side='right')
        ttk.Button(row, text='Restore selected', style='Accent.TButton', command=restore).pack(side='right', padx=8)
        ui.center_on(win, self.root)

    # ------------------------------------------------------------------ Datasheet Builder tab
    def build_datasheet_builder_tab(self):
        self.dsb_panel = datasheet_builder_ui.DatasheetBuilderPanel(self.dsb_frame, on_saved=self._dsb_saved, status=self.status)
        self.dsb_panel.pack(fill='both', expand=True)

    def _dsb_saved(self):
        """A datasheet was saved, deleted, restored or imported: the Procedures list is refreshed (the runnable spec has changed)."""
        self.refresh()

    # ------------------------------------------------------------------ Datasheets tab
    def build_datasheets_tab(self):
        area = self.datasheets_frame
        ttk.Label(area, text='Import Cal Processor .MDD files as read-only templates. You can review everything before it is saved, '
                             'and the embedded scripts are never executed.', style='Muted.TLabel', wraplength=950, justify='left').pack(anchor='w', pady=(0, 10))
        buttons = ttk.Frame(area)
        buttons.pack(fill='x', pady=(0, 10))
        ttk.Button(buttons, text='Import .MDD...', style='Accent.TButton', command=self.choose_mdd).pack(side='left', padx=(0, 8))
        ttk.Button(buttons, text='View test points', command=self.view_imported_points).pack(side='left', padx=(0, 8))
        ttk.Button(buttons, text='Refresh', command=self.refresh_datasheets).pack(side='left')
        cols = ('id', 'manufacturer', 'model', 'procedure', 'points', 'filename', 'date')
        self.ds_table = ui.make_table(area, cols, ('ID', 'Manufacturer', 'Model', 'Procedure', 'Points', 'Source file', 'Imported'),
                                      (50, 140, 150, 160, 70, 380, 150), zebra=True, anchors={'manufacturer': 'w', 'model': 'w', 'procedure': 'w', 'filename': 'w'},
                                      stretch={'id': False, 'points': False, 'date': False})
        self.empty_ds = self._empty_state(self.ds_table, 'No datasheets imported yet.\nPress "Import .MDD..." to add your first one.')
        self.ds_table.bind('<Double-1>', lambda _: self.view_imported_points())
        self.ds_status = tk.StringVar(value='No datasheet selected.')
        self.refresh_datasheets()

    def refresh_datasheets(self):
        for item in self.ds_table.get_children():
            self.ds_table.delete(item)
        with sqlite3.connect(DB) as conn:
            init_datasheet_db(conn)
            rows = conn.execute('''SELECT id,manufacturer,model,procedure_name,test_count,source_filename,imported_at
                                 FROM datasheet_templates ORDER BY imported_at DESC,id DESC''').fetchall()
        for n, row in enumerate(rows):
            self.ds_table.insert('', 'end', iid=str(row[0]), values=row, tags=('even' if n % 2 == 0 else 'odd',))
        self._toggle_empty(self.ds_table, not rows)
        self.status.set(f'{len(rows)} imported datasheet(s).')

    def choose_mdd(self):
        path = filedialog.askopenfilename(title='Choose Cal Processor datasheet', filetypes=[('Cal Processor datasheet', '*.mdd *.MDD'), ('All files', '*.*')])
        if not path:
            return
        try:
            parsed = parse_mdd(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Cannot read datasheet', str(exc), parent=self.root)
            return
        h = parsed['header']
        win = ui.dialog(self.root, 'Preview MDD import - review before saving')
        ui.fit_window(win, 1180, 660, min_w=800, min_h=480)
        head = ttk.Frame(win, padding=(16, 14, 16, 6)); head.pack(fill='x')
        ttk.Label(head, text=f"{h.get('Manufacturer', '').strip()}  {h.get('Model', '').strip()}", style='Header.TLabel').pack(side='left')
        ui.Pill(head, f"{len(parsed['points'])} test points", 'info').pack(side='right')
        ttk.Label(win, text=f"Procedure: {h.get('Procedure_Name', '').strip() or '-'}", style='Muted.TLabel').pack(anchor='w', padx=16)
        ui.Notice(win, 'Original nominal values, limits, readings and specifications are preserved exactly. Check them against the source before approving.', 'info').pack(fill='x', padx=16, pady=10)
        bar = ttk.Frame(win, padding=12)
        bar.pack(side='bottom', fill='x')
        body = ttk.Frame(win, padding=(16, 0)); body.pack(fill='both', expand=True)
        self._point_grid(body, parsed['points'])
        def approve():
            try:
                tid, created, count = import_mdd(DB, path)
            except (OSError, ValueError, sqlite3.Error) as exc:
                messagebox.showerror('Import failed', str(exc), parent=win)
                return
            win.destroy()
            self.refresh_datasheets()
            self.ds_table.selection_set(str(tid))
            self.ds_table.see(str(tid))
            messagebox.showinfo('Datasheet import', f'{count} test points ' + ('saved to database.' if created else 'already imported; no duplicate created.'), parent=self.root)
        ttk.Button(bar, text='Cancel', command=win.destroy).pack(side='right')
        ttk.Button(bar, text='Approve and import', style='Accent.TButton', command=approve).pack(side='right', padx=8)

    def _point_grid(self, parent, points):
        cols = ('no', 'function', 'nominal', 'tolerance', 'low', 'high', 'found', 'left')
        grid = ui.make_table(parent, cols, ('No.', 'Function', 'Nominal', 'Tolerance', 'Low', 'High', 'As found', 'As left'),
                             (55, 260, 190, 255, 90, 90, 90, 90), zebra=True, hscroll=True,
                             anchors={'function': 'w', 'nominal': 'w', 'tolerance': 'w'})
        clean = lambda t: re.sub(r'\s+', ' ', (t or '').replace('~', ' | ')).strip()
        for n, p in enumerate(points, 1):
            grid.insert('', 'end', values=(n, clean(p.get('Text_Function', '')), clean(p.get('Text_Nominal', '')),
                        clean(p.get('Text_Tolerance', '')), p.get('Tol_Low', ''), p.get('Tol_High', ''),
                        p.get('Text_AsFound', ''), p.get('Text_AsLeft', '')), tags=('even' if n % 2 else 'odd',))
        return grid

    def view_imported_points(self):
        sel = self.ds_table.selection()
        if not sel:
            messagebox.showinfo('Select datasheet', 'Select an imported datasheet first.', parent=self.root)
            return
        with sqlite3.connect(DB) as conn:
            row = conn.execute('SELECT manufacturer,model,procedure_name FROM datasheet_templates WHERE id=?', (int(sel[0]),)).fetchone()
            records = conn.execute('SELECT original_fields_json FROM datasheet_test_points WHERE template_id=? ORDER BY point_order', (int(sel[0]),)).fetchall()
        if not row:
            return
        win = ui.dialog(self.root, 'Imported datasheet - ' + ' '.join(str(x) for x in row), modal=False)
        ui.fit_window(win, 1180, 640, min_w=800, min_h=480)
        head = ttk.Frame(win, padding=(16, 14, 16, 8)); head.pack(fill='x')
        ttk.Label(head, text=f'{row[0]} {row[1]}  -  {row[2]}', style='Header.TLabel').pack(side='left')
        ui.Pill(head, f'{len(records)} points', 'info').pack(side='right')
        bar = ttk.Frame(win, padding=12); bar.pack(side='bottom', fill='x')
        ttk.Button(bar, text='Close', command=win.destroy).pack(side='right')
        body = ttk.Frame(win, padding=(16, 0)); body.pack(fill='both', expand=True)
        self._point_grid(body, [json.loads(r[0]) for r in records])

    # ------------------------------------------------------------------ Instruments tab
    def build_instruments_tab(self):
        parent = self.instruments_frame
        searchbar = ttk.Frame(parent)
        searchbar.pack(fill='x', pady=(0, 10))
        ttk.Label(searchbar, text='Find').pack(side='left')
        self.instrument_search = tk.StringVar()
        ttk.Entry(searchbar, textvariable=self.instrument_search, width=34).pack(side='left', padx=(8, 6))
        self.instrument_search.trace_add('write', lambda *_: self.refresh_instruments())
        ttk.Label(searchbar, text='asset ID, model or serial number', style='Small.TLabel').pack(side='left', padx=(2, 8))
        ttk.Button(searchbar, text='Clear', style='Quiet.TButton', command=lambda: self.instrument_search.set('')).pack(side='left')
        ttk.Button(searchbar, text='New instrument...', style='Accent.TButton', command=self.new_instrument).pack(side='right')
        cols = ('asset', 'manufacturer', 'model', 'serial', 'interval', 'procedure', 'last', 'due')
        self.instrument_table = ui.make_table(parent, cols, ('Instrument ID', 'Manufacturer', 'Model', 'Serial number', 'Interval (months)', 'Assigned procedure', 'Last report', 'Next due'),
                                              (140, 130, 110, 140, 100, 260, 100, 110), zebra=True,
                                              anchors={'asset': 'w', 'manufacturer': 'w', 'model': 'w', 'serial': 'w', 'procedure': 'w'})
        self.empty_inst = self._empty_state(self.instrument_table, 'No instruments yet.\nPress "New instrument..." to register your first one.')
        self.instrument_table.bind('<Double-1>', lambda _: self.edit_instrument())
        self.instrument_table.bind('<<TreeviewSelect>>', lambda _: self._sync_instrument_buttons())
        bar = ttk.Frame(parent)
        bar.pack(fill='x', pady=(12, 0))
        self.btn_i_launch = ttk.Button(bar, text='▶  Launch assigned procedure', style='Accent.TButton', command=self.launch_instrument_procedure)
        self.btn_i_demo = ttk.Button(bar, text='Demo', command=lambda: self.launch_instrument_procedure(demo=True))
        self.btn_i_edit = ttk.Button(bar, text='Edit...', command=self.edit_instrument)
        self.btn_i_delete = ttk.Button(bar, text='Delete', command=self.delete_instrument)
        for b in (self.btn_i_launch, self.btn_i_demo, self.btn_i_edit):
            b.pack(side='left', padx=(0, 8))
        self.btn_i_delete.pack(side='right')
        self.instrument_status = tk.StringVar(value='')

    def _sync_instrument_buttons(self):
        state = 'normal' if self.instrument_table.selection() else 'disabled'
        for b in (self.btn_i_launch, self.btn_i_demo, self.btn_i_edit, self.btn_i_delete):
            b.configure(state=state)

    def refresh_instruments(self):
        if not hasattr(self, 'instrument_table'):
            return
        term = self.instrument_search.get().strip()
        with sqlite3.connect(DB) as conn:
            rows = conn.execute('''SELECT i.id,i.asset_id,i.manufacturer,i.model,i.serial_number,
                     i.interval_months,COALESCE(p.name,'Not assigned')
                     FROM instruments i LEFT JOIN procedures p ON p.id=i.procedure_id
                     WHERE (?='' OR i.asset_id LIKE ? OR i.model LIKE ? OR i.serial_number LIKE ?)
                     ORDER BY i.asset_id''', (term, *(['%' + term + '%'] * 3))).fetchall()
        previous = self.instrument_table.selection()
        for iid in self.instrument_table.get_children():
            self.instrument_table.delete(iid)
        for n, row in enumerate(rows):
            iid, asset, mfg, model, serial, interval, proc = row
            runs = labregistry.runs_for(asset)
            due, _ = labregistry.next_due(asset) if runs else (None, None)
            late = bool(due and due < datetime.date.today())
            self.instrument_table.insert('', 'end', iid=str(iid), values=(asset, mfg, model, serial, interval if interval is not None else '', proc,
                                                                          runs[0]['run_at'][:10] if runs else '', (due.isoformat() + (' OVERDUE' if late else '')) if due else ''),
                                         tags=(('overdue',) if late else ('even' if n % 2 == 0 else 'odd',)))
        self.instrument_table.tag_configure('overdue', background=ui.C['bad_bg'], foreground=ui.C['bad'])
        self._toggle_empty(self.instrument_table, not rows)
        if rows and not term:
            self.empty_inst.configure(text='No instruments yet.\nPress "New instrument..." to register your first one.')
        if not rows and term:
            self.empty_inst.configure(text='No instruments match your search.')
        if previous and self.instrument_table.exists(previous[0]):
            self.instrument_table.selection_set(previous[0])
        self._sync_instrument_buttons()
        self.instrument_status.set(f'{len(rows)} instrument(s) displayed.')

    def selected_instrument(self):
        selected = self.instrument_table.selection()
        if not selected:
            messagebox.showinfo('Select instrument', 'Select an instrument from the Instruments tab first.')
            return None
        with sqlite3.connect(DB) as conn:
            return conn.execute('SELECT id,asset_id,manufacturer,model,serial_number,interval_months,procedure_id,notes FROM instruments WHERE id=?', (int(selected[0]),)).fetchone()

    def new_instrument(self):
        self.instrument_editor(None)

    def edit_instrument(self):
        item = self.selected_instrument()
        if item:
            self.instrument_editor(item)

    def delete_instrument(self):
        item = self.selected_instrument()
        if not item:
            return
        if not messagebox.askyesno('Delete instrument', f'Delete instrument "{item[1]}" from the database?\n\nCalibration results already saved by procedures are not affected.'):
            return
        with sqlite3.connect(DB) as conn:
            conn.execute('DELETE FROM instruments WHERE id=?', (item[0],))
        self.refresh_instruments()
        self.status.set(f'Deleted instrument {item[1]}.')

    def instrument_editor(self, record):
        win = ui.dialog(self.root, 'Edit instrument' if record else 'Register new instrument')
        win.resizable(False, False)
        form = ttk.Frame(win, padding=22)
        form.pack(fill='both', expand=True)
        ttk.Label(form, text='Edit instrument' if record else 'Register new instrument', style='Header.TLabel').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))
        labels = ('Instrument ID *', 'Manufacturer', 'Model', 'Serial number', 'Calibration interval (months)', 'Notes')
        indexes = (1, 2, 3, 4, 5, 7)
        variables = {}
        entries = {}
        for r, (label, index) in enumerate(zip(labels, indexes), 1):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky='w', padx=(0, 16), pady=6)
            v = tk.StringVar(value=str(record[index]) if record and record[index] is not None else '')
            e = ttk.Entry(form, textvariable=v, width=46)
            e.grid(row=r, column=1, pady=6, sticky='ew')
            variables[label.rstrip(' *')] = v
            entries[label.rstrip(' *')] = e
        ttk.Label(form, text='Assigned procedure').grid(row=7, column=0, sticky='w', pady=6)
        with sqlite3.connect(DB) as conn:
            procs = conn.execute('SELECT id,name,model FROM procedures WHERE enabled=1 ORDER BY name').fetchall()
        options = ['(None)'] + [f'{id_}: {name}' for id_, name, _m in procs]
        proc_var = tk.StringVar(value='(None)')
        if record and record[6] is not None:
            proc_var.set(next((x for x in options[1:] if x.startswith(str(record[6]) + ': ')), '(None)'))
        ttk.Combobox(form, textvariable=proc_var, values=options, width=43, state='readonly').grid(row=7, column=1, pady=6, sticky='ew')
        hint = ttk.Label(form, text='', style='Small.TLabel')
        hint.grid(row=8, column=1, sticky='w')
        def suggest(_e=None):
            # Offer the matching procedure when a model is typed and nothing is assigned yet.
            model = variables['Model'].get().strip().lower()
            if model and proc_var.get() == '(None)':
                for (id_, name, pmodel), option in zip(procs, options[1:]):
                    if pmodel and (pmodel.lower() in model or model in pmodel.lower()):
                        proc_var.set(option)
                        hint.configure(text='Procedure suggested from the model - change it if needed.')
                        return
        entries['Model'].bind('<FocusOut>', suggest)
        entries['Instrument ID'].focus_set()
        def save():
            asset = variables['Instrument ID'].get().strip()
            if not asset:
                messagebox.showerror('Required', 'Instrument ID is required.', parent=win); return
            interval_str = variables['Calibration interval (months)'].get().strip()
            try:
                interval = int(interval_str) if interval_str else None
                if interval is not None and interval <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror('Invalid interval', 'Enter a positive whole number of months or leave blank.', parent=win); return
            proc_id = int(proc_var.get().split(':', 1)[0]) if proc_var.get() != '(None)' else None
            values = (asset, variables['Manufacturer'].get().strip(), variables['Model'].get().strip(), variables['Serial number'].get().strip(),
                      interval, proc_id, variables['Notes'].get().strip())
            try:
                with sqlite3.connect(DB) as conn:
                    if record:
                        conn.execute('''UPDATE instruments SET asset_id=?,manufacturer=?,model=?,serial_number=?,interval_months=?,procedure_id=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?''', (*values, record[0]))
                    else:
                        conn.execute('''INSERT INTO instruments(asset_id,manufacturer,model,serial_number,interval_months,procedure_id,notes) VALUES (?,?,?,?,?,?,?)''', values)
            except sqlite3.IntegrityError:
                messagebox.showerror('Duplicate ID', 'That Instrument ID already exists.', parent=win); return
            win.destroy()
            self.refresh_instruments()
            self.status.set(f'Saved instrument {asset}.')
        buttons = ttk.Frame(form)
        buttons.grid(row=9, column=0, columnspan=2, sticky='e', pady=(16, 0))
        ttk.Button(buttons, text='Cancel', command=win.destroy).pack(side='right')
        ttk.Button(buttons, text='Save instrument', style='Accent.TButton', command=save).pack(side='right', padx=8)
        win.bind('<Return>', lambda _: save())
        ui.center_on(win, self.root)

    def launch_instrument_procedure(self, demo=None):
        item = self.selected_instrument()
        if not item:
            return
        instrument_id, asset, _, _, _, _, procedure_id, _ = item
        if procedure_id is None:
            messagebox.showinfo('No procedure assigned', f'Assign a procedure to instrument {asset} first (Edit...).')
            return
        with sqlite3.connect(DB) as conn:
            row = conn.execute('SELECT name,script_path FROM procedures WHERE id=? AND enabled=1', (procedure_id,)).fetchone()
        if not row:
            messagebox.showerror('Procedure unavailable', 'The assigned procedure is missing or disabled.'); return
        name, script = row
        demo = self.demo.get() if demo is None else demo
        if self._launch(name, script, demo, asset=asset):
            self.status.set(f'Launched {name} for instrument {asset}' + (' in demo mode.' if demo else '.') + ' The Instrument ID and serial number are filled in.')


if __name__ == '__main__':
    appdata.migrate_legacy_progress()
    init_db()
    ui.enable_hidpi()
    root = tk.Tk()
    Manager(root)
    root.mainloop()
