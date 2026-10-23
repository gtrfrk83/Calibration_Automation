"""Procedure packages: export one procedure into a zip, inspect a zip, install it.  Tk-free; no instrument I/O.

    pkg = packages.build_package('Fluke_117_Verification', out_dir)                 # tools/make_package.py is the command-line front end
    pv  = packages.inspect(zip_path, library_dir=packages.get_library_dir())        # everything is checked here; nothing is written
    if pv.ok: res = packages.install(zip_path, expected_sha256=pv.zip_sha256)       # backs up, writes, records, locks/unlocks

A package is a zip with `manifest.json` at its root:

    {"package_format": 1,
     "procedure": {"id": "Fluke_117_Verification", "name": "...", "version": "2"},
     "min_suite_version": "v70", "author": "...", "created": "2026-10-22T09:00:00",
     "requires": ["handheld_dmm.py", ...],                       # files the procedure depends on that are NOT in the package (information)
     "files": [{"path": "Procedures/Fluke_117_Verification.py", "sha256": "...", "size": 123}, ...],
     "verified": {"date": "2026-10-20", "who": "Mike", "fingerprint": "...", "note": "..."}}      # optional

Every file of the zip is listed with its sha256, and every listed file is in the zip.  The package holds PYTHON: it is code that will run on this
computer, so it is only ever installed after the person has seen where it came from and what it replaces and has confirmed.

What is refused (nothing at all is written, the reasons are listed in Preview.errors):
    * a missing, unreadable or wrong-version manifest; a file that is not listed, listed but missing, listed twice, or whose sha256 / size is wrong;
    * a path that is absolute, has a drive, backslashes, '..', '.', empty or hidden parts, a ':' (alternate data stream), a Windows device name,
      or is a symbolic link (zip-slip and friends);
    * a file outside Procedures/, specs/, drivers/, diagrams/ and tests/; an executable or database name (.exe .bat .dll .sh .sqlite3 ...) anywhere;
      a type that is not on the short list below; a .py under diagrams/; a Python file that does not parse (it is parsed, never run);
    * a sidecar (Procedures/<id>.procedure.json) that is missing, invalid, disagrees with the manifest, names the same display name as another
      installed procedure, or carries the seeded-verified flag (that flag is the lab owner's attestation: a package can neither add nor remove it);
    * a procedure that needs files this suite does not have (its fingerprint list names a file that is neither in the package nor installed);
    * a package for a newer suite or a newer package format; a zip bigger than the limits below.

Install: every replaced file is first copied to Backups/packages/<folder>/<name>_backup_vNN<ext>; files are written one by one (temporary file, then
rename); if anything fails, the files already written are put back and the import is not recorded.  The import is recorded in the NEW table
`package_imports` of lab_registry.sqlite3 (append-only).  calibration_procedures.sqlite3 is never opened here: the Manager registers a new
procedure in its list the usual way (it scans Procedures/ when the list refreshes).

Verified on hardware: a package that REPLACES files of a procedure that is verified and locked unlocks it (one 'unlock' event, who 'package import'),
unless the package carries a verified mark whose fingerprint equals the fingerprint the installed procedure now has (the files it declares, with the
package's files in place) and the lab has no saved procedure changes for that model; then it is marked verified again ('verify' event, with the mark's
date and name).  The mark is the exporting lab's claim; it proves that the files are the ones that were verified, not that anyone checked a
instrument.  Other locked procedures that depend on a replaced shared file show 'Changed since verification' through the usual fingerprint check.
"""
from __future__ import annotations

import ast
import getpass
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import procscan
import suite_info
import verified

HERE = Path(__file__).resolve().parent
FORMAT = 1
MANIFEST = 'manifest.json'
ALLOWED_DIRS = ('Procedures', 'specs', 'drivers', 'diagrams', 'tests')
ALLOWED_EXT = ('.py', '.json', '.png', '.jpg', '.jpeg', '.txt', '.md', '.csv')
BLOCKED_EXT = ('.exe', '.bat', '.cmd', '.com', '.scr', '.ps1', '.psm1', '.vbs', '.vbe', '.js', '.jse', '.wsf', '.wsh', '.msi', '.dll', '.so', '.dylib',
               '.sh', '.bash', '.jar', '.pyd', '.pyc', '.pyo', '.pyw', '.lnk', '.reg', '.cpl', '.hta', '.sqlite', '.sqlite3', '.db', '.zip', '.app')
MAX_ZIP = 100 * 1024 * 1024
MAX_FILE = 20 * 1024 * 1024
MAX_TOTAL = 60 * 1024 * 1024
MAX_FILES = 500
MAX_MANIFEST = 1024 * 1024
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
IMPORT_WHO = 'package import'

CODE_WARNING = ('This package contains Python program code. Installing it lets that code run on this computer, with your permissions, the next time '
                'a procedure is started. Only import packages from the lab\'s own library folder. If this file came from anywhere else (an email, '
                'a download, a USB stick), cancel.')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS package_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    zip_sha256 TEXT NOT NULL,
    zip_name TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    imported_by TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL,
    files_json TEXT NOT NULL DEFAULT '[]',
    backups_json TEXT NOT NULL DEFAULT '[]',
    unlocked INTEGER NOT NULL DEFAULT 0,
    mark TEXT NOT NULL DEFAULT 'none',
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS package_imports_proc ON package_imports(procedure, id);
CREATE TRIGGER IF NOT EXISTS package_imports_no_update BEFORE UPDATE ON package_imports
BEGIN SELECT RAISE(ABORT, 'package imports are append-only'); END;
CREATE TRIGGER IF NOT EXISTS package_imports_no_delete BEFORE DELETE ON package_imports
BEGIN SELECT RAISE(ABORT, 'package imports are never deleted'); END;
'''


class PackageError(ValueError):
    """Refused, with a plain-language reason."""


# ------------------------------------------------------------------------------------------------------------ paths
def check_member_path(name) -> str:
    """'' when `name` is an acceptable relative path for a package file, else the reason it is refused."""
    if not isinstance(name, str) or not name:
        return 'empty path'
    if '\x00' in name or any(ord(c) < 32 for c in name):
        return 'control characters in the path'
    if '\\' in name:
        return 'backslash in the path'
    if name.startswith('/') or re.match(r'^[A-Za-z]:', name):
        return 'absolute path'
    if ':' in name:
        return "':' in the path"
    parts = name.split('/')
    for part in parts:
        if part == '..':
            return "'..' in the path"
        if part in ('', '.'):
            return 'empty or "." part in the path'
        if part.startswith('.'):
            return 'hidden file or folder name'
        if part != part.rstrip(' .'):
            return 'a name ending in a space or a dot'
        if part.split('.')[0].upper() in RESERVED:
            return 'a Windows device name'
    if len(parts) < 2 or parts[0] not in ALLOWED_DIRS:
        return 'outside the allowed folders (' + ', '.join(d + '/' for d in ALLOWED_DIRS) + ')'
    ext = Path(parts[-1]).suffix.lower()
    if ext in BLOCKED_EXT:
        return f'executable or database file name ({ext})'
    if ext not in ALLOWED_EXT:
        return f'file type {ext or "(none)"} is not allowed'
    if ext == '.py' and parts[0] == 'diagrams':
        return 'a program file in the diagrams folder'
    return ''


def target_path(base, rel) -> Path:
    """Where `rel` lands under `base`; refused if it would leave `base` (symbolic links inside the tree included)."""
    base = Path(base).resolve()
    dest = (base / rel).resolve()
    try:
        dest.relative_to(base)
    except ValueError:
        raise PackageError(f'{rel}: would be written outside the suite folder')
    if (base / rel).is_symlink():
        raise PackageError(f'{rel}: the installed file is a symbolic link')
    return dest


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def suite_number(text) -> int | None:
    m = re.search(r'(\d+)', str(text or ''))
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------------------------------------------------ the library folder setting
def _settings_path(path=None) -> Path:
    return Path(path) if path else Path.home() / '.calibration_suite' / 'packages.json'     # same file ui_theme.Settings('packages') uses


def get_library_dir(settings_path=None) -> str:
    """The configured package library folder ('' = none).  Never raises."""
    try:
        data = json.loads(_settings_path(settings_path).read_text(encoding='utf-8'))
        value = data.get('library_folder', '')
        return value.strip() if isinstance(value, str) else ''
    except (OSError, ValueError, AttributeError):
        return ''


def set_library_dir(folder, settings_path=None) -> None:
    p = _settings_path(settings_path)
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data['library_folder'] = str(folder or '').strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding='utf-8')


def inside(path, folder) -> bool:
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except (ValueError, OSError):
        return False


# ------------------------------------------------------------------------------------------------------------ the preview
@dataclass
class FileItem:
    path: str
    size: int
    sha256: str
    state: str                    # 'new' | 'replace' | 'same'

    @property
    def action_text(self) -> str:
        return {'new': 'New file', 'replace': 'Replaces the installed file (backed up first)', 'same': 'Identical to the installed file'}[self.state]


@dataclass
class Preview:
    zip_path: str = ''
    zip_name: str = ''
    zip_sha256: str = ''
    zip_size: int = 0
    origin: str = ''
    in_library: bool | None = None            # None = no library folder is configured
    library_dir: str = ''
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    proc_id: str = ''
    name: str = ''
    version: str = ''
    author: str = ''
    created: str = ''
    min_suite: str = ''
    files: list = field(default_factory=list)
    requires: list = field(default_factory=list)
    installed_version: str = ''                # '' = this procedure is not installed
    status_kind: str = 'none'                  # the installed procedure's verified-on-hardware state before the import
    status_text: str = ''
    locked_before: bool = False
    will_unlock: bool = False
    mark: dict | None = None
    mark_state: str = 'none'                   # 'none' | 'valid' | 'invalid'
    mark_detail: str = ''
    affected: list = field(default_factory=list)       # [(procedure name, [what changes])] other locked procedures that will show 'changed'
    # private: what install writes
    _data: dict = field(default_factory=dict, repr=False)
    _proc: object = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.proc_id)

    @property
    def replaced(self) -> list:
        return [f.path for f in self.files if f.state == 'replace']

    @property
    def is_update(self) -> bool:
        return bool(self.installed_version) or any(f.state != 'new' for f in self.files)

    def summary_lines(self) -> list:
        out = [f'{self.name} ({self.proc_id}) version {self.version}', f'{len(self.files)} file(s): {sum(f.state == "new" for f in self.files)} new, '
               f'{len(self.replaced)} replaced, {sum(f.state == "same" for f in self.files)} identical']
        return out


@dataclass
class InstallResult:
    proc_id: str
    name: str
    version: str
    written: list
    backups: list                 # [(installed path, backup path)]
    unlocked: bool
    mark_applied: bool
    import_id: int
    notes: list = field(default_factory=list)


# ------------------------------------------------------------------------------------------------------------ reading a package
def _read_zip(zip_path, pv: Preview):
    """Open the zip and return {path: bytes} of every file plus the manifest dict; problems go to pv.errors.  Nothing is written anywhere."""
    p = Path(zip_path)
    try:
        size = p.stat().st_size
    except OSError as ex:
        pv.errors.append(f'The package file cannot be read ({ex.strerror or ex}).')
        return None, None
    pv.zip_size = size
    if size > MAX_ZIP:
        pv.errors.append(f'The package file is too large ({size // (1 << 20)} MB; the limit is {MAX_ZIP // (1 << 20)} MB).')
        return None, None
    try:
        pv.zip_sha256 = sha256_file(p)
        zf = zipfile.ZipFile(p)
    except (OSError, zipfile.BadZipFile) as ex:
        pv.errors.append(f'This is not a readable zip file ({ex}).')
        return None, None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES + 1:
            pv.errors.append(f'Too many files in the package ({len(infos)}; the limit is {MAX_FILES}).')
            return None, None
        total = sum(i.file_size for i in infos)
        if total > MAX_TOTAL or any(i.file_size > MAX_FILE for i in infos):
            pv.errors.append('The files in the package are too large when unpacked (zip bomb protection).')
            return None, None
        data, seen_fold = {}, {}
        for info in infos:
            name = info.filename
            if info.is_dir():
                reason = check_member_path(name.rstrip('/') + '/x.txt') if name.rstrip('/') else 'empty path'
                if reason and 'outside the allowed' not in reason:
                    pv.errors.append(f'{name}: {reason}')
                continue
            if info.flag_bits & 0x1:
                pv.errors.append(f'{name}: the file is encrypted')
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                pv.errors.append(f'{name}: a symbolic link is not allowed')
                continue
            if name != MANIFEST:
                reason = check_member_path(name)
                if reason:
                    pv.errors.append(f'{name}: {reason}')
                    continue
            fold = name.casefold()
            if name in data or fold in seen_fold:
                pv.errors.append(f'{name}: appears twice (or differs from another name only by upper / lower case)')
                continue
            seen_fold[fold] = name
            try:
                raw = zf.read(info)
            except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError) as ex:
                pv.errors.append(f'{name}: cannot be read ({ex})')
                continue
            if len(raw) != info.file_size:
                pv.errors.append(f'{name}: size does not match the zip directory')
                continue
            data[name] = raw
    if MANIFEST not in data:
        pv.errors.append('There is no manifest.json at the root of the package.')
        return None, None
    if len(data[MANIFEST]) > MAX_MANIFEST:
        pv.errors.append('manifest.json is too large.')
        return None, None
    try:
        manifest = json.loads(data.pop(MANIFEST).decode('utf-8-sig'))
    except ValueError as ex:
        pv.errors.append(f'manifest.json is not valid JSON ({ex}).')
        return None, None
    return data, manifest


def _text(d, key, limit=200):
    v = d.get(key, '')
    return v.strip()[:limit] if isinstance(v, str) else ''


def _check_manifest(manifest, data, pv: Preview):
    """Fill pv from the manifest and verify every file against it.  Returns the {path: bytes} of the listed files (or None)."""
    if not isinstance(manifest, dict):
        pv.errors.append('manifest.json is not a JSON object.')
        return None
    fmt = manifest.get('package_format')
    if isinstance(fmt, bool) or not isinstance(fmt, int):
        pv.errors.append('manifest.json has no package_format number.')
        return None
    if fmt > FORMAT:
        pv.errors.append(f'This package was made for a newer package format ({fmt}); this suite reads format {FORMAT}. Update the suite first.')
        return None
    if fmt < 1:
        pv.errors.append(f'Unknown package format {fmt}.')
        return None
    proc = manifest.get('procedure')
    if not isinstance(proc, dict) or not all(isinstance(proc.get(k), str) and proc.get(k).strip() for k in ('id', 'name', 'version')):
        pv.errors.append('manifest.json must give the procedure id, name and version.')
        return None
    pv.proc_id, pv.name, pv.version = proc['id'].strip(), proc['name'].strip(), proc['version'].strip()
    if not procscan.ID_RE.match(pv.proc_id):
        pv.errors.append('The procedure id in the manifest is not a plain name.')
        return None
    pv.author, pv.created = _text(manifest, 'author'), _text(manifest, 'created')
    pv.min_suite = _text(manifest, 'min_suite_version', 40)
    if pv.min_suite:
        need, have = suite_number(pv.min_suite), suite_number(suite_info.VERSION)
        if need is None:
            pv.errors.append(f'The minimum suite version "{pv.min_suite}" is not understood.')
        elif have is not None and need > have:
            pv.errors.append(f'This package needs suite version {pv.min_suite} or newer; this is {suite_info.full_version()}.')
    req = manifest.get('requires', [])
    pv.requires = [r for r in req if isinstance(r, str)][:200] if isinstance(req, list) else []
    listed = manifest.get('files')
    if not isinstance(listed, list) or not listed:
        pv.errors.append('manifest.json lists no files.')
        return None
    out, seen = {}, set()
    for item in listed:
        path = item.get('path') if isinstance(item, dict) else None
        digest = item.get('sha256') if isinstance(item, dict) else None
        reason = check_member_path(path) if isinstance(path, str) else 'not a path'
        if reason:
            pv.errors.append(f'Listed file {path!r}: {reason}')
            continue
        if path in seen:
            pv.errors.append(f'{path}: listed twice in the manifest')
            continue
        seen.add(path)
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            pv.errors.append(f'{path}: the manifest has no valid sha256 for it (checksum missing)')
            continue
        if path not in data:
            pv.errors.append(f'{path}: listed in the manifest but not in the zip')
            continue
        raw = data[path]
        if sha256_bytes(raw) != digest:
            pv.errors.append(f'{path}: checksum does not match the manifest (the file was changed or damaged)')
            continue
        size = item.get('size')
        if size is not None and size != len(raw):
            pv.errors.append(f'{path}: size does not match the manifest')
            continue
        out[path] = raw
    for path in data:
        if path not in seen:
            pv.errors.append(f'{path}: in the zip but not listed in the manifest')
    return out


def _check_code_and_sidecar(files, pv: Preview, base: Path):
    """The sidecar, the parse check of every Python file, the requirements and the name clash.  Fills pv._proc."""
    for path, raw in files.items():
        if path.endswith('.py'):
            try:
                ast.parse(raw.decode('utf-8-sig'), path)
            except (SyntaxError, ValueError, UnicodeDecodeError) as ex:
                pv.errors.append(f'{path}: not valid Python ({ex}); it was only parsed, never run')
    side_path = f'Procedures/{pv.proc_id}{procscan.SIDECAR_SUFFIX}'
    if side_path not in files:
        pv.errors.append(f'The package has no {side_path} (the procedure\'s metadata).')
        return
    try:
        doc = json.loads(files[side_path].decode('utf-8-sig'))
        proc = procscan.parse_sidecar(doc, pv.proc_id)
    except (ValueError, UnicodeDecodeError) as ex:
        pv.errors.append(f'{side_path}: {ex}')
        return
    if proc.seed_verified or (isinstance(doc, dict) and 'seed_order' in doc):
        pv.errors.append(f'{side_path}: a package cannot carry the seeded-verified flag (that is the lab owner\'s own record)')
    if proc.name != pv.name:
        pv.errors.append(f'The name in the manifest ("{pv.name}") differs from the name in {side_path} ("{proc.name}").')
    if proc.version != pv.version:
        pv.errors.append(f'The version in the manifest ({pv.version}) differs from the version in {side_path} ({proc.version}).')
    pv._proc = proc
    if proc.launcher not in files and not (base / proc.launcher).is_file():
        pv.errors.append(f'The launcher {proc.launcher} is neither in the package nor installed.')
    missing = []
    for label in (*proc.fingerprint_code, *proc.fingerprint_spec):
        rel = procscan.split_label(label)[0]
        if rel not in files and not (base / rel).is_file() and rel not in missing:
            missing.append(rel)
    if missing:
        pv.errors.append('This suite does not have files the procedure needs, and the package does not bring them: ' + ', '.join(missing) +
                         '. Install the package that provides them first.')
    pv.requires = sorted((set(pv.requires) | {procscan.split_label(l)[0] for l in (*proc.fingerprint_code, *proc.fingerprint_spec)}) - set(files))
    for other in procscan.scan_folder(base / 'Procedures').procs:
        if other.id.casefold() != proc.id.casefold() and other.name.casefold() == proc.name.casefold():
            pv.errors.append(f'Another installed procedure ({other.id}) already has the display name "{proc.name}".')


def _final_sidecar(files, pv: Preview, base: Path):
    """The sidecar as it will be written: a package can neither add nor remove the seeded-verified flag, so an existing flag is carried over."""
    side = f'Procedures/{pv.proc_id}{procscan.SIDECAR_SUFFIX}'
    current = base / side
    if side not in files or not current.is_file():
        return
    try:
        old = json.loads(current.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return
    if isinstance(old, dict) and old.get('seed_verified'):
        doc = json.loads(files[side].decode('utf-8-sig'))
        doc['seed_verified'] = True
        if 'seed_order' in old:
            doc['seed_order'] = old['seed_order']
        files[side] = (json.dumps(doc, indent=1) + '\n').encode('utf-8')
        pv.warnings.append('This procedure is one of the lab owner\'s seeded verified procedures; that record stays as it is.')


def inspect(zip_path, base=None, registry=None, library_dir=None, suite_version=None) -> Preview:
    """Check a package completely and say what installing it would do.  Writes nothing (reading the verified state may record the usual
    automatic 'changed since verification' unlock of a procedure whose files already changed)."""
    base = Path(base) if base else HERE
    pv = Preview(zip_path=str(zip_path), zip_name=Path(zip_path).name)
    try:
        pv.origin = str(Path(zip_path).resolve())
    except OSError:
        pv.origin = str(zip_path)
    lib = (library_dir or '').strip()
    pv.library_dir = lib
    pv.in_library = None if not lib else inside(zip_path, lib)
    data, manifest = _read_zip(zip_path, pv)
    if data is None:
        return pv
    pv.manifest = manifest if isinstance(manifest, dict) else {}
    files = _check_manifest(manifest, data, pv)
    if files is None or pv.errors:
        if files is not None:
            pv.files = [FileItem(p, len(r), sha256_bytes(r), 'new') for p, r in sorted(files.items())]
        return pv
    _check_code_and_sidecar(files, pv, base)
    if not pv.errors:
        _final_sidecar(files, pv, base)
    reg = registry or verified.Registry(base=base)
    items = []
    for path in sorted(files):
        raw = files[path]
        try:
            dest = target_path(base, path)
        except PackageError as ex:
            pv.errors.append(str(ex))
            continue
        if dest.exists():
            if not dest.is_file():
                pv.errors.append(f'{path}: a folder with this name is installed')
                continue
            state = 'same' if dest.read_bytes() == raw else 'replace'
        else:
            state = 'new'
        items.append(FileItem(path, len(raw), sha256_bytes(raw), state))
    pv.files = items
    pv._data = files
    if pv.errors or pv._proc is None:
        return pv
    # ---- what it means for the procedure that is installed now
    old = procscan.find(pv.proc_id, base)
    pv.installed_version = old.version or '(no version)' if old else ''
    proc = pv._proc
    entry = verified.make_entry(proc.name, proc.model, base / proc.launcher, base)
    st = reg.status(entry)
    pv.status_kind, pv.status_text = st.kind, st.text
    pv.locked_before = st.kind == 'verified'
    pv.will_unlock = pv.locked_before and bool(pv.replaced)
    if pv.locked_before and pv.replaced:
        pv.warnings.append(f'"{proc.name}" is VERIFIED ON HARDWARE and LOCKED. This package replaces {len(pv.replaced)} of its file(s), so it will be unlocked '
                           'and will need hardware re-verification' + (' unless the verified mark in the package is valid (see below).' if pv.manifest.get('verified') else '.'))
    elif pv.locked_before:
        pv.warnings.append(f'"{proc.name}" is verified on hardware and locked. Every file in this package is identical to the installed one, so it stays locked.')
    # the verified mark that travels with the package
    mark = pv.manifest.get('verified')
    if mark is not None:
        pv.mark = mark if isinstance(mark, dict) else {}
        pv.mark_state, pv.mark_detail = _judge_mark(pv, reg, base, files)
    # other locked procedures that depend on a replaced shared file
    pv.affected = _affected(pv, reg, base, files)
    if pv.in_library is False:
        pv.warnings.insert(0, 'This file is NOT inside the lab\'s library folder.')
    elif pv.in_library is None:
        pv.warnings.insert(0, 'No library folder is set, so nothing shows whether this file comes from the lab\'s own library.')
    return pv


def _reader(base: Path, files: dict):
    return lambda rel: files[rel] if rel in files else verified._read(base / rel)


def file_fingerprint(registry, proc, read=None) -> str:
    """The fingerprint a package's verified mark refers to: the declared program and spec files only (no saved procedure changes)."""
    code, spec = registry.file_components(proc, read)
    return registry.definition_hash({'code': code, 'spec': spec, 'overrides': {}})


def _judge_mark(pv: Preview, reg, base: Path, files: dict):
    mark = pv.mark or {}
    who, day, fp = (mark.get(k) for k in ('who', 'date', 'fingerprint'))
    if not all(isinstance(v, str) and v.strip() for v in (who, day, fp)):
        return 'invalid', 'The verified mark is incomplete (it needs a date, a name and a fingerprint), so it is ignored.'
    clean, problems = verified.check_verify_form(who, day)
    if problems:
        return 'invalid', 'The verified mark is ignored: ' + ' '.join(problems)
    proc = pv._proc
    if file_fingerprint(reg, proc, _reader(base, files)) != fp.strip():
        return 'invalid', ('The verified mark does not match: the files this procedure will have here (its own and the shared ones it uses) are not '
                           'the ones that were verified.')
    if reg.override_digests(proc.model):
        return 'invalid', 'The verified mark does not count here: this installation has saved procedure changes for this model, which the mark does not cover.'
    return 'valid', (f'Valid: the files match the fingerprint of the procedure that {clean["who"]} verified on hardware on {clean["on_date"]}. '
                     'This only shows the files are the verified ones; nobody here has checked an instrument.')


def _affected(pv: Preview, reg, base: Path, files: dict) -> list:
    out = []
    read = _reader(base, files)
    for other in procscan.scan_folder(base / 'Procedures').procs:
        if other.id == pv.proc_id:
            continue
        rec = reg.record(other.launcher_name)
        if rec is None or not rec.locked or rec.unreadable:
            continue
        overrides = reg.override_digests(other.model)
        now = reg.file_components(other)                                   # as installed today (already-changed procedures are not news)
        if reg.changes_since(rec, {'code': now[0], 'spec': now[1], 'overrides': overrides}):
            continue
        code, spec = reg.file_components(other, read)
        changes = reg.changes_since(rec, {'code': code, 'spec': spec, 'overrides': overrides})
        if changes:
            out.append((other.name, changes))
    return out


# ------------------------------------------------------------------------------------------------------------ installing
def next_backup(base: Path, rel: str) -> Path:
    """Backups/packages/<folder>/<stem>_backup_vNN<ext> with the first free NN (two digits or more)."""
    r = Path(rel)
    folder = base / 'Backups' / 'packages' / r.parent
    n = 1
    while True:
        cand = folder / f'{r.stem}_backup_v{n:02d}{r.suffix}'
        if not cand.exists():
            return cand
        n += 1


def _atomic_write(dest: Path, raw: bytes):
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.pkg_', suffix='.tmp', dir=str(dest.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def _connect(path):
    con = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    try:
        con.executescript(SCHEMA)
        yield con
    finally:
        con.close()


def install(zip_path, base=None, registry=None, expected_sha256=None, library_dir=None, imported_by=None, now=None) -> InstallResult:
    """Install a package that passes inspect().  `expected_sha256` is the checksum of the zip the person was shown: a different file is refused."""
    base = Path(base) if base else HERE
    reg = registry or verified.Registry(base=base)
    pv = inspect(zip_path, base, reg, library_dir)
    if expected_sha256 and pv.zip_sha256 != expected_sha256:
        raise PackageError('The package file is not the one that was shown in the preview (its checksum changed). Nothing was installed.')
    if not pv.ok:
        raise PackageError('The package was refused: ' + ' '.join(pv.errors))
    proc, who = pv._proc, (imported_by or _user())
    when = (now or datetime.now)().isoformat(timespec='seconds')
    backups, written, created_dirs = [], [], []
    state = {f.path: f.state for f in pv.files}
    # 1. backups of everything that will be replaced, BEFORE anything is written
    try:
        for rel, st in state.items():
            if st != 'replace':
                continue
            src = target_path(base, rel)
            bak = next_backup(base, rel)
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, bak)
            backups.append((rel, str(bak)))
    except OSError as ex:
        raise PackageError(f'The backup of a file that would be replaced could not be made ({ex}). Nothing was installed.')
    entry = verified.make_entry(proc.name, proc.model, base / proc.launcher, base)
    unlock_now = pv.will_unlock
    mark_ok = pv.mark_state == 'valid'
    files_json = json.dumps([{'path': f.path, 'sha256': f.sha256, 'size': f.size, 'state': f.state} for f in pv.files])
    notes = []
    # 2. the record and the files in one go: the record is rolled back if a file cannot be written, and the files if the record cannot be committed
    try:
        with _connect(reg.path) as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                cur = con.execute('INSERT INTO package_imports(procedure,name,version,zip_sha256,zip_name,origin,author,imported_by,imported_at,files_json,'
                                  'backups_json,unlocked,mark,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                  (pv.proc_id, pv.name, pv.version, pv.zip_sha256, pv.zip_name, pv.origin, pv.author, who, when, files_json,
                                   json.dumps(backups), int(unlock_now), pv.mark_state + (': ' + pv.mark_detail if pv.mark_state == 'invalid' else ''),
                                   ('' if pv.replaced else 'no installed file changed') + ('; in library folder' if pv.in_library else '')))
                import_id = cur.lastrowid
                for f in pv.files:
                    if f.state == 'same':
                        continue
                    dest = target_path(base, f.path)
                    existed_dir = dest.parent.exists()
                    _atomic_write(dest, pv._data[f.path])
                    written.append((f.path, f.state))
                    if not existed_dir:
                        created_dirs.append(dest.parent)
                con.execute('COMMIT')
            except BaseException:
                try:
                    con.execute('ROLLBACK')
                except sqlite3.Error:
                    pass
                raise
    except (OSError, sqlite3.Error, PackageError) as ex:
        _roll_back(base, written, backups, created_dirs)
        raise PackageError(f'The package could not be installed ({ex}). The files already written were put back; nothing is recorded.')
    except BaseException:
        _roll_back(base, written, backups, created_dirs)
        raise
    procscan._CACHE.clear()
    # 3. verified on hardware: unlock a replaced locked procedure, then honour a valid mark
    unlocked = applied = False
    if unlock_now:
        try:
            reg.unlock(entry.proc_key, IMPORT_WHO, f'files replaced by package {pv.proc_id} version {pv.version} (zip sha256 {pv.zip_sha256[:12]})')
            unlocked = True
        except verified.VerifyError as ex:
            notes.append(f'Could not record the unlock ({ex}); the procedure will unlock itself when its files are next compared.')
    if mark_ok:
        m = pv.mark
        try:
            reg.verify(entry, str(m['who'])[:80], str(m['date']), f'Verified mark imported with package {pv.proc_id} version {pv.version} '
                       f'(zip sha256 {pv.zip_sha256[:12]}, imported by {who}). It records that the installed files are the verified ones.',
                       str(m.get('hardware', ''))[:500] if isinstance(m.get('hardware', ''), str) else '')
            applied = True
        except verified.VerifyError as ex:
            notes.append(f'The verified mark was not applied ({ex}).')
    return InstallResult(pv.proc_id, pv.name, pv.version, [w[0] for w in written], backups, unlocked, applied, import_id, notes)


def _roll_back(base: Path, written, backups, created_dirs):
    """Put the installed tree back as it was: replaced files from their backups, new files removed, new folders removed when empty."""
    saved = dict(backups)
    for rel, st in reversed(written):
        try:
            dest = target_path(base, rel)
            if st == 'replace' and rel in saved:
                shutil.copy2(saved[rel], dest)
            elif st == 'new':
                dest.unlink()
        except (OSError, PackageError):
            pass
    for d in sorted(set(created_dirs), key=lambda p: -len(p.parts)):
        try:
            d.rmdir()
        except OSError:
            pass


def _user() -> str:
    try:
        return getpass.getuser() or 'unknown'
    except Exception:
        return 'unknown'


def imports(registry_path, procedure=None, limit=200) -> list:
    """Rows of package_imports, newest first (an empty list when nothing was ever imported)."""
    try:
        con = sqlite3.connect(str(registry_path), timeout=5)
        try:
            sql = 'SELECT id,procedure,name,version,zip_sha256,zip_name,origin,author,imported_by,imported_at,files_json,backups_json,unlocked,mark,note FROM package_imports'
            args = ()
            if procedure:
                sql, args = sql + ' WHERE procedure=?', (procedure,)
            cols = ('id', 'procedure', 'name', 'version', 'zip_sha256', 'zip_name', 'origin', 'author', 'imported_by', 'imported_at', 'files', 'backups',
                    'unlocked', 'mark', 'note')
            rows = [dict(zip(cols, r)) for r in con.execute(sql + ' ORDER BY id DESC LIMIT ?', (*args, int(limit)))]
        finally:
            con.close()
    except sqlite3.Error:
        return []
    for r in rows:
        r['files'], r['backups'] = json.loads(r['files'] or '[]'), json.loads(r['backups'] or '[]')
    return rows


# ------------------------------------------------------------------------------------------------------------ exporting
def package_filename(proc) -> str:
    return f'{proc.id}_v{re.sub(r"[^A-Za-z0-9._-]", "_", proc.version or "0")}.zip'


def collect_files(proc, base: Path, extra=(), only=()) -> list:
    """The files that go into the package of `proc`: its own files (sidecar, launcher ...), the diagrams named by its hook-up prefixes, extras.
    `only` (a fix package): just the sidecar (the format needs it) and these files; everything else the procedure uses is listed in `requires`."""
    if only:
        return list(dict.fromkeys([proc.sidecar, *only]))
    paths = [proc.sidecar, proc.launcher, *proc.own_files, *proc.tests, *extra]
    for prefix in proc.diagram_prefixes:
        paths += sorted(f'diagrams/{p.name}' for p in (base / 'diagrams').glob(f'{prefix}_*.png'))
    out = []
    for rel in paths:
        if rel not in out:
            out.append(rel)
    return out


def build_package(proc_id, base=None, out_dir='.', registry=None, extra_files=(), with_verified_mark=False, author='', min_suite=None,
                  created=None, only=()) -> Path:
    """Write the package of one installed procedure and return its path.  The zip is reproducible (fixed time stamps, sorted names)."""
    base = Path(base) if base else HERE
    proc = procscan.find(proc_id, base)
    if proc is None:
        raise PackageError(f'"{proc_id}" is not a registered procedure (no Procedures/<id>.procedure.json).')
    files = {}
    for rel in collect_files(proc, base, extra_files, only):
        reason = check_member_path(rel)
        if reason:
            raise PackageError(f'{rel}: cannot be packaged ({reason}).')
        src = base / rel
        if not src.is_file():
            raise PackageError(f'{rel}: listed for this procedure but not found.')
        files[rel] = src.read_bytes()
    side = proc.sidecar
    doc = json.loads(files[side].decode('utf-8-sig'))
    if doc.get('seed_verified') or 'seed_order' in doc:                       # the lab owner's record stays with the lab owner
        doc.pop('seed_verified', None)
        doc.pop('seed_order', None)
        doc['seed_verified'] = False
        files[side] = (json.dumps(doc, indent=1) + '\n').encode('utf-8')
    mark = None
    if with_verified_mark:
        reg = registry or verified.Registry(base=base)
        entry = verified.make_entry(proc.name, proc.model, base / proc.launcher, base)
        st = reg.status(entry)
        if st.kind != 'verified':
            raise PackageError('A verified mark can only be added for a procedure that is verified on hardware, locked and unchanged since '
                               f'(this one is: {st.text}).')
        if reg.override_digests(proc.model):
            raise PackageError('This model has saved procedure changes, which a package does not carry, so a verified mark would not be true.')
        rec = st.record
        mark = {'date': rec.verified_on, 'who': rec.verified_by, 'fingerprint': file_fingerprint(reg, proc), 'note': 'Exported from the verified record of this lab.'}
        if rec.hardware:
            mark['hardware'] = rec.hardware
    required = sorted({procscan.split_label(l)[0] for l in (*proc.fingerprint_code, *proc.fingerprint_spec)} - set(files))
    manifest = {'package_format': FORMAT, 'procedure': {'id': proc.id, 'name': proc.name, 'version': proc.version},
                'min_suite_version': min_suite or suite_info.VERSION, 'author': author, 'created': created or datetime.now().isoformat(timespec='seconds'),
                'suite_version': suite_info.full_version(), 'requires': required,
                'files': [{'path': p, 'sha256': sha256_bytes(files[p]), 'size': len(files[p])} for p in sorted(files)]}
    if mark:
        manifest['verified'] = mark
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / package_filename(proc)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, raw in [(MANIFEST, (json.dumps(manifest, indent=1) + '\n').encode('utf-8')), *((p, files[p]) for p in sorted(files))]:
            zi = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, raw)
    target.write_bytes(buf.getvalue())
    return target
