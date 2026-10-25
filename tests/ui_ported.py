"""The list of engines already ported to ui_port (tests/ui_ported.txt).  Test helper."""
from pathlib import Path

TXT = Path(__file__).resolve().parent / 'ui_ported.txt'


def entries():
    """{scenario key: [files]}"""
    out = {}
    for line in TXT.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            key, _, files = line.partition(':')
            out[key.strip()] = files.split()
    return out


def keys():
    return sorted(entries())


def files():
    return {f for fs in entries().values() for f in fs}


def engine_files():
    """The engine (or launcher) module of each ported entry: the first file listed."""
    return {k: v[0] for k, v in entries().items()}
