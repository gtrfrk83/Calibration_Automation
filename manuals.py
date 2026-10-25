"""Where the instrument manuals (PDF) are and which one belongs to a model.  Pure Python: no Qt, no database.

Folders searched, in order: CALSUITE_MANUALS (environment variable), <data folder>/manuals, <program folder>/manuals.  Files are matched by model number in the file
name, ignoring case, spaces and punctuation ("5522 manual.pdf" matches 5522A; "33220 Calibration Manual.pdf" matches 33220A).
Nothing is copied, changed or deleted here."""
from __future__ import annotations

import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def folders() -> list[Path]:
    out = []
    env = os.environ.get('CALSUITE_MANUALS', '').strip()
    if env:
        out.append(Path(env).expanduser())
    try:
        import appdata
        out.append(appdata.data_dir() / 'manuals')
    except Exception:
        pass
    out.append(HERE / 'manuals')
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def _norm(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(text).lower())


def all_manuals() -> list[Path]:
    found = []
    for folder in folders():
        try:
            found.extend(sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.pdf'))
        except OSError:
            continue
    return found


def find(model: str) -> list[Path]:
    """The manuals for `model` ('5522A', 'Fluke 8846A', '33220A'); best match first.  A model with a trailing letter also matches the bare number."""
    key = _norm(model)
    if not key:
        return []
    tokens = [t for t in re.findall(r'[a-z]*\d+[a-z]*', str(model).lower())] or [key]
    wanted = []
    for t in tokens:
        t = _norm(t)
        wanted += [t, re.sub(r'[a-z]+$', '', t)]
    wanted = [w for i, w in enumerate(wanted) if len(w) >= 3 and w not in wanted[:i]]
    scored = []
    for p in all_manuals():
        name = _norm(p.stem)
        for rank, w in enumerate(wanted):
            if w in name:
                scored.append((rank, len(name), p))
                break
    scored.sort(key=lambda x: (x[0], x[1], str(x[2])))
    return [p for _r, _n, p in scored]


def page_from_ref(text) -> int | None:
    """The first page number in a reference such as 'Manual page 14', 'p. 8' or 'pp. 15-16'; None if there is none."""
    m = re.search(r'\bp(?:age|p?\.?)\s*(\d+)', str(text), re.I) or re.fullmatch(r'\s*(\d+)\s*', str(text))
    return int(m.group(1)) if m else None
