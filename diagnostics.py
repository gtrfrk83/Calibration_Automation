"""Friendly handling of problems: a missing-package check, and an error window that offers a diagnostic log instead of a traceback.

The diagnostic log holds the error, the suite version, Python/OS versions and the installed package versions.  It never contains
passwords: anything that looks like password=..., pwd: ..., token=... is blanked before it is written.
"""
from __future__ import annotations

import platform
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

import appdata
import suite_info

# (import name, pip name, what it is used for)
PACKAGES = [
    ('pyvisa', 'pyvisa', 'talking to instruments (USB, GPIB, LAN)'),
    ('serial', 'pyserial', 'talking to instruments over RS-232'),
    ('reportlab', 'reportlab', 'PDF reports'),
    ('openpyxl', 'openpyxl', 'Excel exports (only the 8846A and WaveSurfer use it)'),
    ('pypdfium2', 'pypdfium2', 'Procedure Generator: page images of manuals'),
    ('PIL', 'pillow', 'Procedure Generator: page images of manuals'),
    ('anthropic', 'anthropic', 'Procedure Generator: reading manual pages with Claude'),
]
REQUIRED_FOR_DEMO = ('reportlab',)

_SECRET = re.compile(r'(?i)\b(pass(?:word|wd)?|pwd|secret|token|api[_-]?key)\b(\s*[=:]\s*)(\S+)')


def scrub(text: str) -> str:
    """Blank anything that looks like a password or token."""
    return _SECRET.sub(lambda m: f'{m.group(1)}{m.group(2)}<hidden>', text)


def missing_packages():
    out = []
    for module, pip_name, purpose in PACKAGES:
        try:
            __import__(module)
        except Exception:                                  # missing, or present but broken
            out.append((module, pip_name, purpose))
    return out


def package_versions() -> str:
    lines = []
    for module, pip_name, _p in PACKAGES + [('PIL', 'pillow', '')]:
        try:
            m = __import__(module)
            lines.append(f'{pip_name}: {getattr(m, "__version__", getattr(m, "VERSION", "installed"))}')
        except Exception:
            lines.append(f'{pip_name}: not installed')
    return '\n'.join(lines)


def logs_dir() -> Path:
    folder = appdata.data_dir() / 'logs'
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path.home()
    return folder


def write_log(exc_text: str, where: str = '') -> Path:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = logs_dir() / f'diagnostic-{stamp}.txt'
    body = (f'{suite_info.NAME} {suite_info.full_version()} - diagnostic log\n'
            f'Time: {datetime.now().isoformat(timespec="seconds")}\n'
            f'Window: {where}\n'
            f'Python: {sys.version.split()[0]}   OS: {platform.platform()}\n'
            f'Data folder: {appdata.data_dir()}\n\n'
            f'Packages:\n{package_versions()}\n\n'
            f'Error:\n{exc_text}\n')
    path.write_text(scrub(body), encoding='utf-8')
    return path


def explain_missing(missing) -> str:
    lines = ['Some add-on packages this program needs are not installed on this computer:', '']
    for module, pip_name, purpose in missing:
        lines.append(f'   {pip_name}   ({purpose})')
    lines += ['', 'To install them, open a Command Prompt and type:', '',
              '   py -m pip install ' + ' '.join(p for _m, p, _u in missing), '',
              'Then start the program again. If your company blocks pip, ask IT to install the packages above.']
    return '\n'.join(lines)


def install(root, where: str = ''):
    """Make unexpected errors in this window show a plain message with a 'Save diagnostic log' button."""
    from tkinter import messagebox
    state = {'open': False}

    def handler(exc_type, exc, tb):
        text = ''.join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(scrub(text))                              # still visible to anyone running from a console
        if exc_type is KeyboardInterrupt or state['open']:
            return
        state['open'] = True
        try:
            path = write_log(text, where or root.title())
            messagebox.showerror(
                'Something went wrong',
                'The program hit an unexpected problem. Your saved results are not affected.\n\n'
                f'{exc_type.__name__}: {scrub(str(exc))[:300]}\n\n'
                f'A diagnostic log was saved here for support:\n{path}\n\n'
                'You can usually keep working. If it happens again, send that file to your calibration lab support contact.',
                parent=root)
        except Exception:
            pass
        finally:
            state['open'] = False

    root.report_callback_exception = handler
    return handler
