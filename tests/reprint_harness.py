"""Helpers for tests/test_reprint_*.py (not a test module): real engine export code on the simulated benches, a pinned clock, a throw-away lab registry.

Each *_export(out_path) runs the engine's own export_pdf() (the same call the operator's button makes) with only the file dialog and the report dialog
replaced, so the original PDF, its Asset History event and its report snapshot are produced by the production code path.
"""
import contextlib
import importlib
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
for p in (str(ROOT), str(ROOT / 'Procedures'), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
import _tk_stub  # noqa: E402

_tk_stub.install()

import labregistry  # noqa: E402
import report_pdf  # noqa: E402
import report_snapshot  # noqa: E402

FIXED = datetime(2026, 1, 2, 3, 4)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED


class Var:
    def __init__(self, v=''):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


DETAILS = {'technician': 'T. Tech', 'temperature': '23.1 C', 'humidity': '45 %RH',
           'standards': [{'description': 'Fluke 5560A', 'serial': 'S5560', 'due': '2027-01-01'}], 'procedure': 'bench test'}


@contextlib.contextmanager
def registry(db=None):
    """A throw-away lab_registry.sqlite3 and the invariant PDF mode with a pinned clock."""
    import reportlab.rl_config as rc
    rc.invariant = 1
    tmp = tempfile.TemporaryDirectory()
    path = Path(db or Path(tmp.name) / 'lab_registry.sqlite3')
    with mock.patch.object(labregistry, 'DB', path), mock.patch.object(report_pdf, 'datetime', Clock):
        try:
            yield path
        finally:
            tmp.cleanup()


def pdf_text(path):
    return subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout


def last_run_id(asset='A-100'):
    runs = labregistry.runs_for(asset)
    return runs[0]['id'] if runs else None


# ---------------------------------------------------------------------------------------------------------------- engines
@contextlib.contextmanager
def _export_patches(mod, details, out):
    import report_dialog
    with mock.patch.object(report_dialog, 'ask_details', lambda *a, **k: dict(details)), \
            mock.patch.object(getattr(mod, 'filedialog', None) or __import__('ui_port_tk').filedialog, 'asksaveasfilename', lambda **k: str(out)):
        yield


def truevolt_export(out, details=None, demo=False):
    """34470A on the simulated DMM + 5560A bench: the real IO.measure for a fixed sample of points, then the engine's export_pdf()."""
    import truevolt_verification as T
    import golden_engines as ge
    from drivers.simulated import make_dmm_bench
    T.configure('34470A')
    bench, ft, dt = make_dmm_bench('34470A')
    io = T.IO('sim', 'sim', transports=(dt, ft))
    io.reset_at_start()
    app = object.__new__(T.App)
    app.asset, app.serial, app.status, app.root, app.demo = Var('A-100'), Var('SN-1'), Var(), mock.MagicMock(), demo
    app.period = Var('1 year')
    for p in ge.sample(T.POINTS, ge._dmm_key, 14):
        dt.terminals = 'REAR' if p.get('terminal') == 'REAR' else 'FRON'
        with mock.patch.object(T.time, 'sleep', lambda s: None):          # the engine's settle waits are real time
            reading = io.measure(p)
        app.found[str(p['id'])] = dict(reading=reading, result='PASS' if abs(reading - p['nominal']) <= p['error'] else 'FAIL', synthetic=demo,
                                       timestamp=FIXED.isoformat(timespec='seconds'), data='As Found')
    # a few points measured again after an adjustment (As Left)
    for key in list(app.found)[:3]:
        app.left[key] = dict(app.found[key], data='As Left')
    with _export_patches(T, dict(DETAILS, **(details or {})), out):
        app.export_pdf()
    return app


def tds_export(out, details=None):
    """TDS2000C on the simulated scope + calibrator bench (the engine's Runner.run_point), then the engine's export_pdf()."""
    import golden_engines as ge
    import tds2000c_verification as T
    from drivers.simulated_tds import make_tds_bench
    T.SLEEP_SCALE = 0
    bench, t = make_tds_bench('2024C')
    io = T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports={k: v for k, v in t.items() if k != 'dmm'})
    cfg = T.Config('2024C')

    class FakeApp:
        stop = False

        def __init__(self):
            self.io, self.cfg = io, cfg

        def request(self, kind, payload=None):
            return True

        def post(self, *a, **k):
            pass

        def cal_text(self):
            return 'Fluke 5560A'

    io.reset_at_start()
    runner = T.Runner(FakeApp())
    app = object.__new__(T.App)
    app.cfg, app.asset, app.serial, app.status, app.root = cfg, Var('A-100'), Var('SN-2'), Var(), mock.MagicMock()
    pts = [p for p in T.POINTS if cfg.applies(p) and p['kind'] != 'SELFCAL']
    for p in ge.sample(pts, lambda p: p['kind'], 12):
        out_ = runner.run_point(p)
        reading, raw = out_ if isinstance(out_, tuple) else (out_, {})
        raw = dict(raw, reading=reading)
        app.found[str(p['id'])] = dict(reading=reading, raw=raw, result=T.judge(p, reading), synthetic=False, uncertainty=T.uncertainty_text(p, raw),
                                       timestamp=FIXED.isoformat(timespec='seconds'), data='As Found')
    for key in list(app.found)[:2]:
        app.left[key] = dict(app.found[key], data='As Left')
    with _export_patches(T, dict(DETAILS, **(details or {})), out):
        app.export_pdf()
    return app


# ---------------------------------------------------------------------------------------------------------------- comparison
def _streams(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return reader, [page.get_contents().get_data() for page in reader.pages]


def differences(original, reprint, note_prefix):
    """What differs between an original PDF and its reprint, beyond the one footer line `note_prefix...` on each page.  [] means: same pages, same
    text layout (pdftotext -layout) and the reprint's page content is the original's content plus only the appended note drawing."""
    problems = []
    ra, sa = _streams(original)
    rb, sb = _streams(reprint)
    if len(sa) != len(sb):
        return [f'page count {len(sa)} != {len(sb)}']
    for n, (a, b) in enumerate(zip(sa, sb), 1):
        a = a.rstrip()
        if note_prefix is None:                                 # a reprint of the saved record has no note: the page must be identical
            if b.rstrip() != a:
                problems.append(f'page {n}: content stream differs from the original')
            continue
        if not b.startswith(a):
            problems.append(f'page {n}: content stream is not the original plus an appended note')
        elif note_prefix.encode() not in b[len(a):] or b[len(a):].count(b'Tj') != 1:
            problems.append(f'page {n}: the appended part is not exactly one text line with the note')
    if note_prefix is None:
        note_prefix = '\0'
    raw = lambda path: subprocess.run(['pdftotext', '-raw', str(path), '-'], capture_output=True, text=True).stdout   # content order; -layout
    keep = lambda text: '\n'.join(line for line in text.split('\n') if line.strip() and not line.lstrip().startswith(note_prefix))   # aligns columns by page extent
    ta, tb = keep(raw(original)), keep(raw(reprint))
    if ta != tb:
        problems.append('text differs')
    ia, ib = dict(ra.metadata or {}), dict(rb.metadata or {})
    for key in ('/Title', '/Author'):
        if ia.get(key) != ib.get(key):
            problems.append(f'metadata {key}: {ia.get(key)!r} != {ib.get(key)!r}')
    return problems
