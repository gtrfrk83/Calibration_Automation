"""The Calibration Procedure Manager without a toolkit: the procedures database, the list of rows (views, find, category), the selected-procedure card,
the right-click menu rules, the launch command line, the verified-on-hardware actions, the library folder and the backups / restore of a managed script.

    core = ManagerCore()                      # BASE = the folder of this file, DB = appdata.db_path('calibration_procedures.sqlite3')
    core.init_db()
    state = core.list_state(procscan.KIND_VERIFICATION, 'keithley', ALL_CATEGORIES)     # rows + categories + the status / empty texts
    card = core.card(core.row_record(state.rows[0].iid))
    args, cwd = core.launch_args(script, demo=True, fast_demo=False)                      # what the Manager hands to subprocess.Popen

Both Manager windows (the Tk class in Calibration_Procedure_Manager.py and the Qt one in qtui/screens/manager.py) use this module for the database and the
launch rules, so a rule is written once.  The wording of every status text is here too (the Tk Manager's own strings, unchanged).  Nothing here imports a
GUI toolkit and nothing talks to an instrument.
"""
from __future__ import annotations

import datetime
import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import appdata
import dsb_manager      # user-built datasheets are listed (not stored) in the Procedures table
import packages
import procedure_menu
import procmods
import procmods_ui_model
import procscan
import suite_info
import verified
from mdd_importer_v49 import init_datasheet_db      # only the table creation: templates saved by the old Mudcats tab stay in the database

BASE = Path(__file__).resolve().parent
BUILTIN = 'Procedures/WaveSurfer_WS4104HD.py'
VERSION = suite_info.full_version()

ALL_CATEGORIES = 'All categories'
# The Procedures tab has three views: Automated Calibrations (stored kind 'verification'), Manual Calibrations (kind 'manual') and Adjustments (kind 'adjustment').
VIEW_TABS = ((procscan.KIND_VERIFICATION, 'Automated Calibrations'), (procscan.KIND_MANUAL, 'Manual Calibrations'), (procscan.KIND_ADJUSTMENT, 'Adjustments'))
VIEW_NAMES = {procscan.KIND_VERIFICATION: 'Automated Calibrations', procscan.KIND_MANUAL: 'Manual Calibrations', procscan.KIND_ADJUSTMENT: 'Adjustments'}
ADJUSTMENT_NOTE = ("Adjustment changes the instrument's calibration. Adjustment procedures are separate from the calibration checks: "
                   "to check an instrument without changing it, use the Automated Calibrations or Manual Calibrations tab.")
RUN_HINT = 'Run uses real instruments. Demo uses virtual instruments; nothing from a demo is calibration evidence.'
RUN_TIP = 'Run the selected procedure on the real instruments.'
SHORT_VERIFY = {'Mark verified on hardware...': 'Mark verified...', 'Mark verified again...': 'Verify again...', 'Unlock for editing...': 'Unlock...',
                'Lock again (nothing changed)': 'Lock again'}
DEMO_EXPLANATION = ('Run procedure uses real instruments. Demo mode connects VIRTUAL instruments: the windows of a real run appear and commands go to '
                    'simulated instruments, so you can rehearse safely. Nothing from a demo is calibration evidence.')
MANUAL_NOTE = ("Manual calibrations have no instrument automation: you set the standards yourself and type each reading into the test point grid "
               "(Enter saves it and moves to the next point). Import a Mudcats .MDD datasheet to add one.")
EMPTY_LIBRARY = 'No procedures match.\nUse "Register procedure..." to add one.'
START_STATUS = 'Select a procedure, then press Run Procedure.'
LIBRARY_NOT_SET = '(not set: the picker opens in the folder you used last)'
LIBRARY_MENU_LABELS = ('Import Mudcats datasheet (.mdd)...', 'Import procedure package...', 'Register procedure...', None,
                       'Library folder: ', 'Library folder...', None, 'Remove from library')
TAB_STATUS = {
    'procedures': 'Select a procedure, then press Run procedure (or Try in demo mode).',
    'asset_history': 'Every exported PDF report is recorded here. Double-click a test point to see its drift across reports.',
    'standards_specs': 'Published specifications of the calibrators used as standards; they set the lowest uncertainty that may be reported.',
    'datasheet_builder': 'Build your own datasheet from a manufacturer specification; each save is a new version and a runnable procedure.',
}
# the stored text of the columns, in order (key, title)
TABLE_HEADINGS = (('name', 'Procedure'), ('manufacturer', 'Manufacturer'), ('model', 'Model'), ('category', 'Category'), ('ready', 'Status'), ('verified', 'Verified on hardware'))


# ---------------------------------------------------------------------------------------------------------------------------------------------
# module-level helpers the Tk Manager keeps under their old names
# ---------------------------------------------------------------------------------------------------------------------------------------------
def scan_tables(base=None):
    """(found, STABLE, VERSIONS): the registered procedures in list order and the two legacy tables (procscan.py)."""
    found = procscan.procs(base or BASE)
    stable, versions = procscan.legacy_tables(found)
    return found, stable, versions


def init_db(db, base, records):
    """Create the tables and register the scanned procedures.  `records` = the scan's `registration` tuples (name, manufacturer, model, category, launcher file)
    in list order.  Existing procedure IDs and instrument assignments are kept on upgrade."""
    base = Path(base)
    with sqlite3.connect(db) as conn:
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
        # Stable paths are relative to the Manager, and remain unchanged after updates.
        for name, mfr, model, category, filename in records:
            stable = str(Path('Procedures') / filename)
            if not (base / stable).is_file():
                continue
            # Keep existing procedure IDs and instrument assignments on upgrade.
            matches = conn.execute('SELECT id,script_path FROM procedures WHERE name=? ORDER BY id', (name,)).fetchall()
            if matches:
                chosen = matches[0][0]
                # If another record already uses the stable path, preserve it.
                occupied = conn.execute('SELECT id FROM procedures WHERE script_path=?', (stable,)).fetchone()
                if occupied and occupied[0] != chosen:
                    chosen = occupied[0]
                else:
                    conn.execute('UPDATE procedures SET script_path=?,enabled=1 WHERE id=?', (stable, chosen))
                # Remove duplicates only if no instruments point to them; otherwise retain with disabled status.
                for duplicate_id, _ in matches:
                    if duplicate_id != chosen:
                        conn.execute('UPDATE instruments SET procedure_id=? WHERE procedure_id=?', (chosen, duplicate_id))
                        conn.execute('DELETE FROM procedures WHERE id=?', (duplicate_id,))
            else:
                # Also migrate renamed V54 starter registrations by model/category.
                legacy = None
                if filename == 'Fluke_8846A_Verification.py':
                    legacy = conn.execute("SELECT id FROM procedures WHERE model='8846A' AND category='Digital Multimeter' ORDER BY id LIMIT 1").fetchone()
                if legacy:
                    conn.execute('UPDATE OR IGNORE procedures SET name=?,script_path=?,enabled=1 WHERE id=?', (name, stable, legacy[0]))
                else:
                    conn.execute("INSERT OR IGNORE INTO procedures(name,manufacturer,model,category,script_path,description) VALUES(?,?,?,?,?,?)",
                                 (name, mfr, model, category, stable, 'Standalone calibration procedure'))


def display_path(base, path):
    p = Path(path).expanduser().resolve()
    try:
        return str(p.relative_to(base))
    except ValueError:
        return str(p)


def script_file(base, script):
    """Absolute path of a registered script (relative paths are relative to the Manager's folder)."""
    path = Path(script)
    if not path.is_absolute():
        path = Path(base) / path
    return path.resolve()


def can_show_location():
    return sys.platform in ('win32', 'darwin') or shutil.which('xdg-open') is not None


# ---------------------------------------------------------------------------------------------------------------------------------------------
# value objects
# ---------------------------------------------------------------------------------------------------------------------------------------------
@dataclass
class ProcRow:
    """One row of the Procedures table (what the Tk Manager put into its Treeview, plus the tags as plain fields)."""
    iid: str
    name: str
    manufacturer: str
    model: str
    category: str
    script: str
    kind: str
    found: bool
    n_mod: int
    status: str                 # 'Ready' / 'Missing' + '  [user datasheet tag]' + '  MODIFIED (n)'
    verified: str               # verified.Status.text
    vkind: str                  # verified.Status.kind ('none' | 'verified' | 'changed' | 'unlocked')
    user: bool = False

    @property
    def tags(self):
        """The Tk Treeview tags (colour rules): missing -> bad, modified -> warn, verified (and found, unmodified) -> good."""
        return (([] if self.found else ['missing']) + (['modified'] if self.n_mod else []) +
                (['verified'] if self.vkind == 'verified' and self.found and not self.n_mod else []))

    @property
    def tone(self):
        return 'bad' if not self.found else 'warn' if self.n_mod else None


@dataclass
class ListState:
    rows: list
    in_view: int                # rows of this view before find / category
    categories: list            # sorted categories of this view
    category: str               # the category in force (reset to ALL_CATEGORIES when it is not in this view any more)
    empty_text: str
    status: str                 # the status-bar sentence after a refresh
    elsewhere: dict = field(default_factory=dict)


@dataclass
class Card:
    """The Selected-procedure card (refresh_details of the Tk Manager)."""
    selected: bool
    name: str = 'No procedure selected'
    sub: str = 'Pick one from the list.'
    desc: str = ''
    path: str = ''
    ready_text: str = ''
    ready_tone: str = 'neutral'
    run_enabled: bool = False
    mod_text: str = ''
    ver_pill: str = ''
    ver_tone: str = 'neutral'
    ver_text: str = ''
    info_enabled: bool = False
    verify_text: str = ''
    verify_full: str = ''
    verify_enabled: bool = False
    lock_text: str = ''
    lock_full: str = ''
    lock_enabled: bool = False


class ManagerCore:
    view_kind = procscan.KIND_VERIFICATION

    def __init__(self, base=None, db=None, registry=None):
        self.base = Path(base) if base else BASE
        self.db = Path(db) if db else appdata.db_path('calibration_procedures.sqlite3')
        self.procedures = self.base / 'Procedures'
        self.backups = self.base / 'Backups'
        self.registry = registry
        self.stable, self.versions = {}, {}
        self.scanned = {}
        self.user = {}
        self._mods = {}
        self._ver_cache = {}
        self.scan()

    # ------------------------------------------------------------------ database
    def scan(self):
        found = procscan.procs(self.base)
        stable, versions = procscan.legacy_tables(found)
        self.stable.clear(); self.stable.update(stable)
        self.versions.clear(); self.versions.update(versions)
        return found

    def init_db(self):
        init_db(self.db, self.base, [p.registration for p in self.scan()])

    def script_file(self, script):
        return script_file(self.base, script)

    def display_path(self, path):
        return display_path(self.base, path)

    def connect(self):
        return sqlite3.connect(self.db)

    # ------------------------------------------------------------------ verified on hardware (verified.py)
    def verified(self):
        if self.registry is None:
            self.registry = verified.Registry()
        return self.registry

    def ver_entry(self, rec):
        id_, name, _mfr, model, _cat, script = rec[:6]
        user = self.user.get(str(id_))
        return verified.make_entry(name, model, script, self.base, user_uid=user['uid'] if user else None, spec_path=user['spec_path'] if user else '')

    def ver_status(self, rec):
        """(entry, Status) read afresh from the registry: another window may have unlocked it since the list was drawn."""
        entry = self.ver_entry(rec)
        return entry, self.verified().status(entry)

    def mark_verified(self, rec, form):
        """Record a verification (the form is verified_ui's answer).  Returns (record, status text); raises verified.VerifyError."""
        entry, _status = self.ver_status(rec)
        record = self.verified().verify(entry, form['who'], form['on_date'], form['note'], form['hardware'])
        return record, f'"{entry.name}" is marked verified on hardware ({record.verified_on}) and locked against edits.'

    def unlock(self, rec, form):
        entry, _status = self.ver_status(rec)
        record = self.verified().unlock(entry.proc_key, form['who'], form['reason'])
        return record, f'"{entry.name}" is unlocked for editing; the reason is recorded.'

    def relock(self, rec, who):
        entry, _status = self.ver_status(rec)
        record = self.verified().relock(entry, who)
        return record, f'"{entry.name}" is locked again.'

    # ------------------------------------------------------------------ the list
    def mod_counts(self, refresh=False):
        """{model: n} of saved model-wide procedure changes (one query per list refresh; never blocks the list if the registry is unreadable)."""
        if refresh or not self._mods:
            try:
                self._mods = procmods_ui_model.model_counts(procmods.Store())
            except Exception:
                self._mods = {}
        return self._mods

    def kind_of(self, id_, name, category, script):
        """'verification' | 'manual' | 'adjustment' of a list row: the sidecar's kind (or its category / name default), the kind saved with a user-built
        datasheet, the same text rule for any other."""
        if dsb_manager.is_user_iid(id_):
            kind = (self.user.get(str(id_)) or {}).get('kind')
            return kind if kind in procscan.KINDS else procscan.KIND_VERIFICATION
        if not script:
            return procscan.KIND_VERIFICATION
        proc = self.scanned.get(Path(str(script)).name.casefold())
        if proc is not None:
            return proc.effective_kind
        return procscan.classify(name, category)

    def list_state(self, view_kind, term='', category=ALL_CATEGORIES, *, init=True):
        """Everything the Tk Manager's refresh() computes: database registration, the rows of the view, find / category filters, verification statuses."""
        if init:
            self.init_db()
        with self.connect() as conn:
            rows = conn.execute('SELECT id,name,manufacturer,model,category,script_path FROM procedures WHERE enabled=1 ORDER BY manufacturer,model,name').fetchall()
        self.user = {r['iid']: r for r in dsb_manager.user_rows()}          # user-built datasheets: listed after the library rows, never written to the database
        rows = rows + [(r['iid'], r['name'], r['manufacturer'], r['model'], r['category'], r['script']) for r in self.user.values()]
        self.scanned = {p.launcher_name.casefold(): p for p in procscan.procs(self.base)}
        kinds = {r[0]: self.kind_of(r[0], r[1], r[4], r[5]) for r in rows}
        in_view = [r for r in rows if kinds[r[0]] == view_kind]
        cats = sorted({r[4] for r in in_view if r[4]})
        if category != ALL_CATEGORIES and category not in cats:
            category = ALL_CATEGORIES
        term = (term or '').strip().lower()
        mods = self.mod_counts(refresh=True)
        match = lambda r: not (category != ALL_CATEGORIES and r[4] != category) and not (term and term not in ' '.join((r[1], r[2], r[3], r[4])).lower())  # noqa: E731
        listed = [r for r in in_view if match(r)]
        elsewhere = {k: sum(1 for r in rows if kinds[r[0]] == k and match(r)) for k in VIEW_NAMES if k != view_kind} if term else {}
        elsewhere = {k: n for k, n in elsewhere.items() if n}
        entries = [self.ver_entry(r) for r in listed]
        self._ver_cache = self.verified().statuses(entries)          # one registry read; fingerprints only for verified procedures
        out = []
        for (id_, name, mfr, model, cat, script), entry in zip(listed, entries):
            found = script_file(self.base, script).is_file()
            n_mod = mods.get((model or '').casefold(), 0)
            vstat = self._ver_cache.get(entry.proc_key)
            status = ('Ready' if found else 'Missing') + (f'  [{dsb_manager.TAG}]' if dsb_manager.is_user_iid(id_) else '') + \
                     (f'  {procmods_ui_model.chip_text(n_mod)}' if n_mod else '')
            out.append(ProcRow(str(id_), name, mfr, model, cat, script, kinds[id_], found, n_mod, status,
                               vstat.text if vstat is not None else 'Not verified', vstat.kind if vstat is not None else 'none', dsb_manager.is_user_iid(id_)))
        text = EMPTY_LIBRARY
        if not out and elsewhere:
            other = ', '.join(f'{n} in the {VIEW_NAMES[k]} tab' for k, n in elsewhere.items())
            text = f'No procedures match in this tab.\nMatches: {other}.'
        return ListState(out, len(in_view), cats, category, text, f'{len(out)} of {len(in_view)} procedure(s) shown. Double-click a procedure to run it.', elsewhere)

    def row_record(self, iid):
        """(id, name, manufacturer, model, category, script, description) of a row iid (the Tk Manager's _selected_row), None when it is gone."""
        if iid is None:
            return None
        iid = str(iid)
        if dsb_manager.is_user_iid(iid):
            u = self.user.get(iid)
            return (u['iid'], u['name'], u['manufacturer'], u['model'], u['category'], u['script'], u['description']) if u else None
        with self.connect() as conn:
            return conn.execute('SELECT id,name,manufacturer,model,category,script_path,description FROM procedures WHERE id=?', (int(iid),)).fetchone()

    def db_record(self, iid):
        """(name, script_path) of an enabled database row (the Tk Manager's selected()), None for a user datasheet or a missing row."""
        if iid is None or dsb_manager.is_user_iid(str(iid)):
            return None
        with self.connect() as conn:
            return conn.execute('SELECT name,script_path FROM procedures WHERE id=? AND enabled=1', (int(iid),)).fetchone()

    def managed_record(self, iid):
        if iid is None or dsb_manager.is_user_iid(str(iid)):
            return None
        with self.connect() as conn:
            return conn.execute('SELECT id,name,script_path FROM procedures WHERE id=?', (int(iid),)).fetchone()

    # ------------------------------------------------------------------ the card
    def card(self, rec):
        if not rec:
            return Card(selected=False)
        id_, name, mfr, model, cat, script, desc = rec
        user = self.user.get(str(id_))
        found = script_file(self.base, script).is_file() and (user is None or Path(user['spec_path']).is_file())
        version = self.versions.get(Path(script).name)
        c = Card(selected=True, name=name, sub='  |  '.join(x for x in (f'{mfr} {model}'.strip(), cat) if x), desc=desc or '',
                 path=(f'File: {script}' + (f'   (version {version})' if version else '') if user is None else
                       f'User-built datasheet v{user["version"]}   |   spec: {user["spec_path"]}'),
                 ready_text='Ready to run' if found else 'Script file not found', ready_tone='good' if found else 'bad', run_enabled=found)
        n = self.mod_counts().get((model or '').casefold(), 0)
        c.mod_text = procmods_ui_model.chip_text(n) if n else ''
        entry, status = self.ver_status(rec)
        c.ver_pill, c.ver_tone = status.pill, status.tone
        c.ver_text = '\n'.join(status.detail_lines())
        c.info_enabled = True
        state = verified.ui_state(status)
        (c.verify_full, c.verify_enabled), (c.lock_full, c.lock_enabled) = state['verify'], state['lock']
        c.verify_text, c.lock_text = SHORT_VERIFY.get(c.verify_full, c.verify_full), SHORT_VERIFY.get(c.lock_full, c.lock_full)
        return c

    # ------------------------------------------------------------------ right-click menu
    def available_backups(self, rec):
        folder = self.backups / str(rec[0])
        return sorted(folder.glob('*.py'), reverse=True) if folder.exists() else []

    def managed_path(self, record):
        if not record:
            return None
        p = Path(record[2])
        if p.is_absolute():
            return None
        path = (self.base / p).resolve()
        # Restrict replacement to the managed Procedures directory.
        try:
            path.relative_to(self.procedures.resolve())
        except ValueError:
            return None
        return path if path.suffix.lower() == '.py' else None

    def row_menu_items(self, rec, card, can_show=None):
        """procedure_menu entries for a row (None without one); the enabled rules are the card's buttons' own."""
        if not rec:
            return None
        script = rec[5]
        user = self.user.get(str(rec[0]))
        found = script_file(self.base, script).is_file() and (user is None or Path(user['spec_path']).is_file())
        record = self.managed_record(rec[0])
        managed = self.managed_path(record)
        restorable = bool(managed and managed.is_file() and self.available_backups(record))      # a managed script with at least one saved backup
        can_show = can_show_location() if can_show is None else can_show
        return procedure_menu.items(found, (card.verify_full or card.verify_text, card.verify_enabled), (card.lock_full or card.lock_text, card.lock_enabled),
                                    can_show and script_file(self.base, script).is_file(), has_path=bool(script), restorable=restorable)

    # ------------------------------------------------------------------ launching
    def launch_args(self, script, demo, fast_demo=False, asset=None, extra=None):
        """(argv, cwd) exactly as the Tk Manager's _launch hands them to subprocess.Popen; None when the script file is missing."""
        path = script_file(self.base, script)
        if not path.is_file():
            return None
        args = [sys.executable, str(path)]
        if demo:
            args.append('--demo')
            if fast_demo:
                args.append('--fast-demo')
        if asset:
            args += ['--asset', asset]
        args += list(extra or [])
        return args, str(path.parent)

    def readiness_command(self, rec):
        """argv of the readiness check of a row (tools/readiness_check.py on the simulated bench), None when the tool is missing."""
        tool = self.base / 'tools' / 'readiness_check.py'
        if not rec or not tool.is_file():
            return None
        return [sys.executable, str(tool), str(rec[0])]

    # ------------------------------------------------------------------ register / remove
    def register(self, script, name, manufacturer='', model='', category='', description=''):
        """Add a script to the library.  Raises sqlite3.IntegrityError when it is registered already."""
        with self.connect() as conn:
            conn.execute('''INSERT INTO procedures (name,manufacturer,model,category,script_path,description)
                            VALUES (?,?,?,?,?,?)''', (name, manufacturer, model, category, self.display_path(script), description))

    def remove(self, iid):
        with self.connect() as conn:
            conn.execute('DELETE FROM procedures WHERE id=?', (int(iid),))

    # ------------------------------------------------------------------ library folder
    def library_folder_text(self):
        folder = packages.get_library_dir()
        return folder if folder else LIBRARY_NOT_SET

    # ------------------------------------------------------------------ backups / restore of a managed script
    @staticmethod
    def validated_update(source):
        source = Path(source)
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

    def backup(self, rec, path):
        folder = self.backups / str(rec[0]); folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup = folder / f'{stamp}_{path.stem}.py'
        shutil.copy2(path, backup)
        return backup

    @staticmethod
    def atomic_replace(raw, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.update_', suffix='.py', dir=str(target.parent))
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

