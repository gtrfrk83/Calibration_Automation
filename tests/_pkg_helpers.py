"""Test helpers for the package tests: small throw-away suite trees copied from the real one, and hand-made zips.  Test helper only."""
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import procscan  # noqa: E402


def copy_files(dest: Path, rels):
    for rel in rels:
        src = ROOT / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)


def make_tree(dest, proc_ids=(), shared_for=(), keep_own_of=()):
    """A throw-away suite folder holding the whole of `proc_ids` (sidecar, launcher, everything they declare), and only the SHARED files
    (not the procedure's own ones) of `shared_for`."""
    dest = Path(dest)
    (dest / 'Procedures').mkdir(parents=True, exist_ok=True)
    for pid in proc_ids:
        p = procscan.find(pid, ROOT)
        copy_files(dest, [p.sidecar, p.launcher, *(procscan.split_label(l)[0] for l in (*p.fingerprint_code, *p.fingerprint_spec)), *p.own_files])
    for pid in shared_for:
        p = procscan.find(pid, ROOT)
        own = set(p.own_files)
        copy_files(dest, [procscan.split_label(l)[0] for l in (*p.fingerprint_code, *p.fingerprint_spec) if procscan.split_label(l)[0] not in own])
    return dest


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def craft_zip(path, files: dict, manifest=None, proc=None, raw_entries=None, listed=None, **manifest_kw):
    """Write a package by hand. `files` {path: bytes}; the manifest lists them with correct checksums unless `listed` overrides the list;
    `raw_entries` [(zip name, bytes)] are added to the zip without being checked or listed."""
    proc = proc or {'id': 'Keithley_2000_Verification', 'name': 'Keithley 2000 Performance Verification', 'version': '1'}
    man = {'package_format': 1, 'procedure': proc, 'min_suite_version': 'v70', 'author': 'tester', 'created': '2026-10-22T09:00:00',
           'files': listed if listed is not None else [{'path': p, 'sha256': sha(r), 'size': len(r)} for p, r in sorted(files.items())]}
    man.update(manifest_kw)
    if manifest is not None:
        man = manifest
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', json.dumps(man))
        for p, r in files.items():
            zf.writestr(p, r)
        for p, r in (raw_entries or []):
            zf.writestr(p, r)
    return Path(path)


def read_zip(path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def rewrite_zip(path, edit):
    """Rebuild a zip after edit(dict name -> bytes) changed its members (the manifest is NOT refreshed unless the edit does it)."""
    members = read_zip(path)
    edit(members)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for n, r in members.items():
            zf.writestr(n, r)
    Path(path).write_bytes(buf.getvalue())
