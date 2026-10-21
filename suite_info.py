"""One place for the suite's name, version and edition, so every window and report shows the same thing."""
NAME = 'Calibration Suite'
VERSION = 'v70'
EDITION = 'Beta 1'            # '' for the released working copy; the beta keeps its own data folder (see appdata.py)


def full_version() -> str:
    return f'{VERSION} {EDITION}'.strip()


def window_title(procedure: str) -> str:
    """e.g. 'Calibration Suite  |  Fluke 8846A Verification  |  v70 Beta 1'"""
    parts = [NAME, procedure, full_version()]
    return '  |  '.join(p for p in parts if p)
