"""One place for the suite's name, version and edition, so every window and report shows the same thing."""
import functools
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
NAME = 'Calibration Suite'
VERSION = 'v70'
EDITION = 'Beta 2'            # '' for the released working copy; the beta keeps its own data folder (see appdata.py)


def full_version() -> str:
    return f'{VERSION} {EDITION}'.strip()


@functools.lru_cache(maxsize=1)
def build_id() -> str:
    """The commit this copy was built from, e.g. 'be3b199 2026-11-03' (owner, 2026-11-04: a technician said he ran the latest build while the error showed an older
    one, and the title only said 'v70'). `git archive` and GitHub's Download ZIP fill BUILD.txt in (.gitattributes export-subst); a git checkout asks git; '' when
    neither works (the title then shows the version alone)."""
    try:
        text = (_HERE / 'BUILD.txt').read_text(encoding='utf-8').strip()
    except OSError:
        text = ''
    if text and not text.startswith('$Format'):
        return text
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        r = subprocess.run(['git', 'log', '-1', '--format=%h %cs'], cwd=_HERE, capture_output=True, text=True, timeout=5, creationflags=flags)
        return r.stdout.strip() if r.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def title_version() -> str:
    """The version as window titles show it: 'v70 Beta 2 · be3b199 2026-11-03'."""
    build = build_id()
    return f'{full_version()} \u00b7 {build}' if build else full_version()


def window_title(procedure: str) -> str:
    """e.g. 'Calibration Suite  |  Fluke 8846A Verification  |  v70 Beta 1 · be3b199 2026-11-03'"""
    parts = [NAME, procedure, title_version()]
    return '  |  '.join(p for p in parts if p)


DEFAULT_THEME = 'dark' if EDITION else 'light'     # the beta looks like the redesign; the released working copy stays light
