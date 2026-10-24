"""Calibration Procedure Manager v59. Standard-library launcher and SQLite catalog.

Run: python Calibration_Procedure_Manager.py
Standalone procedures remain runnable independently.

Keep ui_theme.py and mdd_importer_v49.py in the same folder as this file.
"""
import datetime
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
from mdd_importer_v49 import init_datasheet_db      # only the table creation: templates saved by the old Mudcats tab stay in the database (read-only, no longer viewable)
import appdata
import suite_info
import labregistry
import labregistry_ui
import specmanager_ui
import procmods
import procmods_ui_model
import datasheet_builder_ui
import mdd_import_ui    # import preview: a Mudcats .MDD becomes a manual calibration procedure
import dsb_manager      # user-built datasheets are listed (not stored) in the Procedures table
import packages          # procedure packages: export / inspect / install a procedure as a zip (packages.py)
import packages_ui
import procedure_menu    # the right-click menu of a Procedures row (which entries, and when they are enabled)
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
# The Procedures tab has three views (tabs): Automated Calibrations (stored kind 'verification': the value is unchanged so no sidecar, package or
# registry row needs a migration), Manual Calibrations (kind 'manual': no instrument automation, readings are typed into the grid) and Adjustments (label only; the stored kind stays 'adjustment').
# A procedure's view comes from its sidecar `kind` or, left out, from its category / name (procscan.classify); user-built datasheets take the kind saved with
# them (all-manual or imported from a .MDD = manual); unknown scripts are automated.
VIEW_TABS = ((procscan.KIND_VERIFICATION, '  Automated Calibrations  '), (procscan.KIND_MANUAL, '  Manual Calibrations  '),
             (procscan.KIND_ADJUSTMENT, '  Adjustments  '))
VIEW_NAMES = {procscan.KIND_VERIFICATION: 'Automated Calibrations', procscan.KIND_MANUAL: 'Manual Calibrations', procscan.KIND_ADJUSTMENT: 'Adjustments'}
ADJUSTMENT_NOTE = ("Adjustment changes the instrument's calibration. Adjustment procedures are separate from the calibration checks: "
                   "to check an instrument without changing it, use the Automated Calibrations or Manual Calibrations tab.")
RUN_HINT = 'Run uses real instruments. Demo uses virtual instruments; nothing from a demo is calibration evidence.'
RUN_TIP = 'Run the selected procedure on the real instruments.'
# short card-button texts; the full text of each stays as the button's tooltip and in the row menu (verified.ui_state gives the full ones)
SHORT_VERIFY = {'Mark verified on hardware...': 'Mark verified...', 'Mark verified again...': 'Verify again...', 'Unlock for editing...': 'Unlock...',
                'Lock again (nothing changed)': 'Lock again'}
DEMO_EXPLANATION = ('Run procedure uses real instruments. Demo mode connects VIRTUAL instruments: the windows of a real run appear and commands go to '
                    'simulated instruments, so you can rehearse safely. Nothing from a demo is calibration evidence.')
MANUAL_NOTE = ("Manual calibrations have no instrument automation: you set the standards yourself and type each reading into the test point grid "
               "(Enter saves it and moves to the next point). Import a Mudcats .MDD datasheet to add one.")


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
        ui.fit_window(root, 1260, 800, min_w=900, min_h=580)
        self.demo = tk.BooleanVar(value=False)
        self.fast_demo = tk.BooleanVar(value=False)       # demo without windows or commands (the old quick demo)
        self.status = tk.StringVar(value='Select a procedure, then press Run Procedure.')
        self.search = tk.StringVar()
        self.category = tk.StringVar(value=ALL_CATEGORIES)

        banner = ui.Banner(root, 'Calibration Procedure Manager', 'Run, document and maintain your calibration procedures')
        banner.pack(fill='x')
        banner.add_pill('Database: ' + DB.name, 'info')
        ui.StatusBar(root, self.status, right=VERSION).pack(side='bottom', fill='x')
        ui.dock_button(root, 'Find instruments...', self.find_instruments)      # a tool for every tab: which VISA resource / GPIB channel each instrument is on

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True)
        ui.TabStrip(self.notebook)
        self.library_frame = ttk.Frame(self.notebook, padding=16)
        self.history_frame = self._scroll_page()
        self.specs_frame = self._scroll_page()
        self.dsb_frame = self._scroll_page()
        self.notebook.add(self.library_frame, text='  Procedures  ')
        self.notebook.add(self.history_frame, text='  Asset History  ')
        self.notebook.add(self.specs_frame, text='  Standards Specs  ')
        self.notebook.add(self.dsb_frame, text='  Datasheet Builder  ')
        self.build_library_tab()
        self.build_library_menu()
        self.build_datasheet_builder_tab()
        self.history_panel = labregistry_ui.HistoryPanel(self.history_frame.content)
        self.history_panel.pack(fill='both', expand=True)
        self.specs_panel = specmanager_ui.SpecManagerPanel(self.specs_frame.content)
        self.specs_panel.pack(fill='both', expand=True)
        ui.polish(root)
        self.notebook.bind('<<NotebookTabChanged>>', self._tab_changed)
        self.refresh()
        root.bind('<Control-f>', lambda _e: (self.notebook.select(self.library_frame), self.search_entry.focus_set()))

    def _scroll_page(self):
        """A tab page that scrolls when its content is taller than the window (ui.ScrollFrame); put the content in `.content`."""
        page = ui.ScrollFrame(self.notebook)
        page.content = ttk.Frame(page.body, padding=16)
        page.content.pack(fill='both', expand=True)
        return page

    def find_instruments(self):
        import instrument_scan_ui
        instrument_scan_ui.open_find_instruments(self.root)

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
        elif tab is self.history_frame:
            self.history_panel.refresh()
            self.status.set('Every exported PDF report is recorded here. Double-click a test point to see its drift across reports.')
        elif tab is self.specs_frame:
            self.specs_panel.refresh()
            self.status.set('Published specifications of the calibrators used as standards; they set the lowest uncertainty that may be reported.')
        elif tab is self.dsb_frame:
            self.dsb_panel.refresh()
            self.status.set('Build your own datasheet from a manufacturer specification; each save is a new version and a runnable procedure.')

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
        self.view_notes = {procscan.KIND_ADJUSTMENT: ui.Notice(outer, text=ADJUSTMENT_NOTE, kind='warn'),
                           procscan.KIND_MANUAL: ui.Notice(outer, text=MANUAL_NOTE, kind='info')}
        self.adjust_note = self.view_notes[procscan.KIND_ADJUSTMENT]
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(10, 8))
        ttk.Label(bar, text='Find').pack(side='left')
        self.search_entry = ttk.Entry(bar, textvariable=self.search, width=30)
        self.search_entry.pack(side='left', padx=(8, 12))
        self.search.trace_add('write', lambda *_: self.refresh())
        self.category_box = ttk.Combobox(bar, textvariable=self.category, width=26, state='readonly', values=[ALL_CATEGORIES])
        self.category_box.pack(side='left')
        self.category_box.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
        ttk.Button(bar, text='Clear', style='Quiet.TButton', command=lambda: (self.search.set(''), self.category.set(ALL_CATEGORIES))).pack(side='left', padx=6)

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
        self.table.bind('<<TreeviewSelect>>', lambda _: self.refresh_details())
        self.table.bind('<Return>', lambda _: self.run_selected())

        card = ttk.LabelFrame(split, text='Selected procedure', padding=(8, 4, 8, 6))
        card.grid(row=0, column=1, sticky='nsew', padx=(14, 0))
        card.configure(width=ui.px(370))
        # Run / demo and the verification buttons are PINNED (never inside the scrolling part, so a short window never hides them); the title, description
        # and file info above them scroll when the window is too short for them
        pinned = ttk.Frame(card)
        pinned.pack(side='bottom', fill='x')                       # packed first: it keeps its height however short the window is
        self.card_scroll = ui.ScrollFrame(card, width=ui.px(340))
        self.card_scroll.pack(side='top', fill='both', expand=True)
        body = self.card_scroll.body
        self.lib_folder = tk.StringVar(value=self.library_folder_text())
        self.d_name = tk.StringVar(); self.d_sub = tk.StringVar(); self.d_desc = tk.StringVar(); self.d_path = tk.StringVar()
        ttk.Label(body, textvariable=self.d_name, style='Section.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w')
        ttk.Label(body, textvariable=self.d_sub, style='Muted.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w', pady=(2, 6))
        self.d_pill = ui.Pill(body, '', 'neutral')
        self.d_pill.pack(anchor='w')
        self.d_desc_label = ttk.Label(body, textvariable=self.d_desc, wraplength=ui.px(300), justify='left')
        self.d_desc_label.pack(anchor='w', pady=(8, 4))
        ttk.Label(body, textvariable=self.d_path, style='Small.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w')
        self.d_mod = ui.Pill(body, '', 'warn')                    # 'MODIFIED (n)': saved model-wide procedure changes exist
        # pinned block: status line, Run / demo, verification buttons
        ttk.Separator(pinned).pack(fill='x', pady=(4, 2))
        ver_row = ttk.Frame(pinned)
        ver_row.pack(anchor='w')
        self.d_ver = ui.Pill(ver_row, '', 'neutral')               # the one-line status: 'VERIFIED ON HARDWARE <date> - LOCKED' / 'CHANGED SINCE' / 'UNLOCKED' / 'NOT VERIFIED'
        self.d_ver.pack(side='left')
        self.d_ver_text = tk.StringVar()                           # the full text (verified.Status.detail_lines): shown by the info button, not on the card
        self.btn_ver_info = ttk.Button(ver_row, text='\u24d8', style='Quiet.TButton', width=2, command=self.show_verified_details)
        self.btn_ver_info.pack(side='left', padx=(6, 0))
        ui.Tooltip(self.btn_ver_info, 'Show the full verification record')
        run_row = ttk.Frame(pinned)
        run_row.pack(fill='x', pady=(2, 0))
        run_row.columnconfigure(0, weight=2, uniform='run')
        run_row.columnconfigure(1, weight=3, uniform='run')
        self.btn_run = ttk.Button(run_row, text='\u25b6 Run', style='AccentCompact.TButton', command=self.run_selected)
        self.btn_run.grid(row=0, column=0, sticky='ew', padx=(0, 3))
        self.btn_demo = ttk.Button(run_row, text='Try in demo mode', style='Compact.TButton', command=lambda: self.run_selected(demo=True))
        self.btn_demo.grid(row=0, column=1, sticky='ew', padx=(3, 0))
        ui.Tooltip(self.btn_run, RUN_TIP)
        ui.Tooltip(self.btn_demo, DEMO_EXPLANATION)
        ttk.Checkbutton(pinned, text='Fast demo (no windows)', variable=self.fast_demo).pack(anchor='w', pady=(2, 0))
        ttk.Label(pinned, text=RUN_HINT, style='Small.TLabel', wraplength=ui.px(300), justify='left').pack(anchor='w', pady=(2, 0))
        ver_btns = ttk.Frame(pinned)
        ver_btns.pack(fill='x', pady=(4, 0))
        ver_btns.columnconfigure((0, 1), weight=1, uniform='ver')
        self.btn_verify = ttk.Button(ver_btns, text='Mark verified...', style='Compact.TButton', command=self.mark_verified)
        self.btn_verify.grid(row=0, column=0, sticky='ew', padx=(0, 3))
        self.btn_lock = ttk.Button(ver_btns, text='Unlock...', style='Compact.TButton', command=self.toggle_lock)
        self.btn_lock.grid(row=0, column=1, sticky='ew', padx=(3, 0))
        for b in (self.btn_verify, self.btn_lock):
            b.full_text = ''
            ui.Tooltip(b, lambda b=b: b.full_text)
        self._build_row_menu_bindings()

    # ------------------------------------------------------------------ Library menu (menu bar, immediately left of Help)
    LIBRARY_MENU_LABELS = ('Import Mudcats datasheet (.mdd)...', 'Import procedure package...', 'Register procedure...', None,
                           'Library folder: ', 'Library folder...', None, 'Remove from library')

    def build_library_menu(self):
        """The import / register / library folder / remove actions (they were a button row on the Procedures tab).  The menu is added to the window's menu bar
        before branding adds Help (on idle), so it sits immediately left of Help.  Handlers are the old buttons' own."""
        try:
            existing = self.root['menu']
            bar = self.root.nametowidget(existing) if existing else tk.Menu(self.root)
        except tk.TclError:
            bar = tk.Menu(self.root)
        menu = tk.Menu(bar, tearoff=False, postcommand=self.refresh_library_menu)
        menu.add_command(label='Import Mudcats datasheet (.mdd)...', command=self.import_mdd_procedure)
        menu.add_command(label='Import procedure package...', command=self.import_package)
        menu.add_command(label='Register procedure...', command=self.add)
        menu.add_separator()
        menu.add_command(label='Library folder: ', state='disabled')               # info line (text refreshed when the menu opens)
        menu.add_command(label='Library folder...', command=self.choose_library_folder)
        menu.add_separator()
        menu.add_command(label='Remove from library', command=self.remove)
        bar.add_cascade(label='Library', menu=menu, underline=0)                  # Alt+L
        self.root.configure(menu=bar)
        self.library_menu = menu
        self.refresh_library_menu()

    def refresh_library_menu(self):
        """Enabled states when the menu opens: Remove from library needs a selected procedure; the info line shows the current library folder."""
        menu = self.library_menu
        menu.entryconfigure(4, label='Library folder: ' + self.library_folder_text())
        menu.entryconfigure(7, state='normal' if self.table.selection() else 'disabled')

    # ------------------------------------------------------------------ right-click menu of a procedure row
    def _build_row_menu_bindings(self):
        for seq in ('<Button-3>', '<Button-2>', '<Control-Button-1>'):         # right click (middle button / Ctrl-click on macOS)
            self.table.bind(seq, self._row_menu_pointer, add='+')
        for seq in ('<Shift-F10>', '<Key-Menu>'):                               # the keyboard: Shift+F10 / the Menu key, on the selected row
            try:
                self.table.bind(seq, self._row_menu_key, add='+')
            except tk.TclError:
                pass

    def _row_menu_pointer(self, event):
        row = self.table.identify_row(event.y)
        if not row:
            return 'break'
        self.table.focus_set()
        self.table.selection_set(row)
        self.table.focus(row)
        self.refresh_details()                                  # the card and the buttons follow the row right away (the menu reads their state)
        self.post_row_menu(event.x_root, event.y_root)
        return 'break'

    def _row_menu_key(self, _event=None):
        sel = self.table.selection()
        if not sel:
            return 'break'
        self.table.see(sel[0])
        self.table.update_idletasks()
        box = self.table.bbox(sel[0])
        x = self.table.winfo_rootx() + (box[0] + 24 if box else 24)
        y = self.table.winfo_rooty() + (box[1] + box[3] if box else 24)
        self.refresh_details()
        self.post_row_menu(x, y)
        return 'break'

    def _can_show_location(self):
        return sys.platform in ('win32', 'darwin') or shutil.which('xdg-open') is not None

    def row_menu_items(self):
        """procedure_menu entries for the selected row (None without one); the enabled rules are the card's buttons' own."""
        rec = self._selected_row()
        if not rec:
            return None
        script = rec[5]
        user = self._user_rows().get(str(rec[0]))
        found = script_file(script).is_file() and (user is None or Path(user['spec_path']).is_file())
        state = lambda b: (b.full_text or str(b.cget('text')), str(b.cget('state')) != 'disabled')  # noqa: E731
        record = self._selected_record()
        managed = self._managed_path(record)
        restorable = bool(managed and managed.is_file() and self._available_backups(record))      # a managed script with at least one saved backup
        return procedure_menu.items(found, state(self.btn_verify), state(self.btn_lock), self._can_show_location() and script_file(script).is_file(),
                                    has_path=bool(script), restorable=restorable)

    def build_row_menu(self):
        entries = self.row_menu_items()
        if entries is None:
            return None
        actions = {procedure_menu.RUN: self.run_selected, procedure_menu.DEMO: lambda: self.run_selected(demo=True), procedure_menu.READINESS: self.readiness_check,
                   procedure_menu.VERIFY: self.mark_verified, procedure_menu.LOCK: self.toggle_lock, procedure_menu.REMOVE: self.remove, procedure_menu.RESTORE: self.restore_previous,
                   procedure_menu.COPY_NAME: self.copy_procedure_name, procedure_menu.COPY_PATH: self.copy_procedure_path,
                   procedure_menu.SHOW: self.show_procedure_location}
        menu = ui.themed_menu(self.table)
        for e in entries:
            if e is None:
                menu.add_separator()
            else:
                menu.add_command(label=e.label, command=actions[e.key], state='normal' if e.enabled else 'disabled')
        return menu

    def post_row_menu(self, x_root, y_root):
        menu = self.build_row_menu()
        if menu is None:
            return None
        self._row_menu = menu
        menu.bind('<Escape>', lambda _e: menu.unpost(), add='+')
        ui.post_menu(menu, x_root, y_root)
        return menu

    def _copy(self, text, what):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set(f'Copied the {what} to the clipboard.')

    def copy_procedure_name(self):
        rec = self._selected_row()
        if rec:
            self._copy(str(rec[1]), 'procedure name')

    def copy_procedure_path(self):
        rec = self._selected_row()
        if rec and rec[5]:
            self._copy(str(script_file(rec[5])), 'file path')

    def show_procedure_location(self):
        rec = self._selected_row()
        if not rec or not rec[5]:
            return
        path = script_file(rec[5])
        if not path.is_file():
            messagebox.showerror('Procedure not found', f'Cannot locate the procedure script:\n{path}')
            return
        try:
            if sys.platform == 'win32':
                subprocess.Popen(['explorer', '/select,', str(path)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', str(path)])
            else:
                subprocess.Popen(['xdg-open', str(path.parent)])
        except OSError as exc:
            messagebox.showerror('Could not open the folder', str(exc))

    def readiness_check(self):
        """Readiness check of the selected procedure on the simulated bench (tools/readiness_check.py in a subprocess; no instrument I/O)."""
        rec = self._selected_row()
        tool = BASE / 'tools' / 'readiness_check.py'
        if not rec or not tool.is_file():
            messagebox.showinfo('Readiness check', 'tools/readiness_check.py was not found next to the Manager.')
            return
        self.status.set(f'Readiness check of {rec[1]} ...')
        out = []

        def work():
            try:
                r = subprocess.run([sys.executable, str(tool), str(rec[0])], capture_output=True, text=True, timeout=300, cwd=str(BASE))
                out.append((r.stdout or '') + (r.stderr or ''))
            except (OSError, subprocess.SubprocessError) as exc:
                out.append(f'The readiness check could not run: {exc}')

        def show():
            win = tk.Toplevel(self.root)
            win.title(f'Readiness check - {rec[1]}')
            box = tk.Text(win, width=110, height=36, wrap='none', font=('Courier New', 9) if sys.platform == 'win32' else 'TkFixedFont')
            box.insert('1.0', out[0])
            box.configure(state='disabled')
            box.pack(fill='both', expand=True)
            self.status.set('Readiness check finished.')

        import threading
        th = threading.Thread(target=work, daemon=True)
        th.start()

        def poll():
            show() if not th.is_alive() else self.root.after(200, poll)
        self.root.after(200, poll)

    def _view_changed(self, _event=None):
        kind = next((k for k, page in self.view_pages.items() if str(page) == self.view_nb.select()), procscan.KIND_VERIFICATION)
        if kind == self.view_kind:
            return
        self.view_kind = kind
        self.category.set(ALL_CATEGORIES)                       # the category list belongs to the view
        for k, note in self.view_notes.items():
            if k == kind:
                note.pack(fill='x', pady=(8, 0), after=self.view_nb)
            else:
                note.pack_forget()
        self.refresh()

    def _kind_of(self, id_, name, category, script):
        """'verification' (Automated Calibrations) | 'manual' | 'adjustment' of a list row: the sidecar's kind (or its category / name default) for a scanned
        procedure, the kind saved with a user-built datasheet, the same text rule for any other."""
        if dsb_manager.is_user_iid(id_):
            kind = (self._user_rows().get(str(id_)) or {}).get('kind')
            return kind if kind in procscan.KINDS else procscan.KIND_VERIFICATION
        if not script:
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
            self.btn_ver_info.configure(state='disabled')
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
            self.d_mod.pack(anchor='w', pady=(6, 0), before=self.d_desc_label)
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
        self.btn_ver_info.configure(state='normal')
        state = verified.ui_state(status)
        for button, key in ((self.btn_verify, 'verify'), (self.btn_lock, 'lock')):
            text, enabled = state[key]
            button.full_text = text                                  # the full wording (tooltip, row menu); the card button shows the short one
            button.configure(text=SHORT_VERIFY.get(text, text), state='normal' if enabled else 'disabled')
        return status

    def show_verified_details(self):
        """The full verification text (who, when, notes, what changed) in a small window under the info button: selectable, closes on Esc or a click elsewhere."""
        text = self.d_ver_text.get().strip()
        if not text:
            return None
        old = getattr(self, '_ver_pop', None)
        if old is not None and old.winfo_exists():
            old.destroy()
            self._ver_pop = None
            return None
        win = tk.Toplevel(self.root)
        self._ver_pop = win
        win.title('Verification record')
        win.transient(self.root)
        win.configure(background=ui.C['border'])
        box = tk.Text(win, width=52, wrap='word', borderwidth=0, highlightthickness=0, padx=ui.px(10), pady=ui.px(8), background=ui.C['card'],
                      foreground=ui.C['text'], insertbackground=ui.C['text'], selectbackground=ui.C['select'], selectforeground=ui.C['text'],
                      font='TkDefaultFont', cursor='arrow')
        box.insert('1.0', text)
        box.configure(height=min(16, max(3, sum(len(x) // 46 + 1 for x in text.split('\n')))), state='disabled')
        box.pack(padx=1, pady=1, fill='both', expand=True)
        win.update_idletasks()
        b = self.btn_ver_info
        x = min(b.winfo_rootx(), max(0, win.winfo_screenwidth() - win.winfo_reqwidth() - 8))
        y = b.winfo_rooty() + b.winfo_height() + 4
        if y + win.winfo_reqheight() > win.winfo_screenheight() - 8:
            y = max(0, b.winfo_rooty() - win.winfo_reqheight() - 4)
        win.geometry(f'+{x}+{y}')
        self._ver_box = box

        def close(_e=None):
            if win.winfo_exists():
                win.destroy()
            self._ver_pop = None

        def focus_left(_e=None):
            win.after(120, lambda: None if not win.winfo_exists() or str(win.focus_get()).startswith(str(win)) else close())
        win.bind('<Escape>', close)
        win.bind('<FocusOut>', focus_left)
        box.bind('<Escape>', close)
        win.after(50, lambda: (win.focus_force(), box.focus_set()) if win.winfo_exists() else None)
        return win

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
        elsewhere = {k: sum(1 for r in rows if kinds[r[0]] == k and match(r)) for k in VIEW_NAMES if k != self.view_kind} if term else {}
        elsewhere = {k: n for k, n in elsewhere.items() if n}
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
            other = ', '.join(f'{n} in the {VIEW_NAMES[k]} tab' for k, n in elsewhere.items())
            text = f'No procedures match in this tab.\nMatches: {other}.'
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

    # ------------------------------------------------------------------ procedure packages (packages.py)
    LIBRARY_NOT_SET = '(not set: the picker opens in the folder you used last)'

    def library_folder_text(self):
        folder = packages.get_library_dir()
        return folder if folder else self.LIBRARY_NOT_SET

    def _show_library_folder(self):
        self.lib_folder.set(self.library_folder_text())

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

    def _available_backups(self, rec):
        folder = BACKUPS / str(rec[0])
        return sorted(folder.glob('*.py'), reverse=True) if folder.exists() else []

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
            win.destroy(); self.refresh(); self.status.set(f'Restored {rec[1]} from {source.name}')
            messagebox.showinfo('Restored', 'Previous procedure restored. Reopen any running procedure windows.')
        row = ttk.Frame(win); row.pack(fill='x', padx=16, pady=14)
        ttk.Button(row, text='Cancel', command=win.destroy).pack(side='right')
        ttk.Button(row, text='Restore selected', style='Accent.TButton', command=restore).pack(side='right', padx=8)
        ui.center_on(win, self.root)

    # ------------------------------------------------------------------ Datasheet Builder tab
    def build_datasheet_builder_tab(self):
        self.dsb_panel = datasheet_builder_ui.DatasheetBuilderPanel(self.dsb_frame.content, on_saved=self._dsb_saved, status=self.status)
        self.dsb_panel.pack(fill='both', expand=True)

    def _dsb_saved(self):
        """A datasheet was saved, deleted, restored or imported: the Procedures list is refreshed (the runnable spec has changed)."""
        self.refresh()

    # ------------------------------------------------------------------ Mudcats .MDD import (Procedures tab button; the old Mudcats tab was removed)
    def import_mdd_procedure(self, path=None):
        """Import a Mudcats .MDD as a MANUAL calibration procedure (mdd_import_ui: preview first, nothing is created until it is approved)."""
        path = path or filedialog.askopenfilename(title='Choose Cal Processor datasheet', filetypes=[('Cal Processor datasheet', '*.mdd *.MDD'), ('All files', '*.*')])
        if not path:
            return None
        return mdd_import_ui.open_preview(self.root, path, on_created=self._mdd_procedure_created, status=self.status)

    def _mdd_procedure_created(self, res):
        """The new manual procedure is in the registry: show it (Manual Calibrations tab, selected)."""
        self.view_nb.select(self.view_pages[procscan.KIND_MANUAL])
        self.search.set('')
        self.category.set(ALL_CATEGORIES)
        self.refresh()
        iid = dsb_manager.IID_PREFIX + res.uid
        if self.table.exists(iid):
            self.table.selection_set(iid)
            self.table.see(iid)


if __name__ == '__main__':
    appdata.migrate_legacy_progress()
    init_db()
    ui.enable_hidpi()
    root = tk.Tk()
    Manager(root)
    root.mainloop()
