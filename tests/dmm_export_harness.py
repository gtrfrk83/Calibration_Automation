"""Headless driver for the multimeter engines' PDF / CSV export code (no tkinter, no instruments).

dump(root, outdir, show) imports each engine from the source tree `root` with tkinter stubbed, fills it with the readings its own --demo mode
produces (deterministic, labelled synthetic; a few failing points are given an As Left reading), pins the clock, and runs the engine's real
export_pdf() / export() with the file dialogs and the report dialog stubbed.  Returns {engine: {'pdf': Path, 'csv': Path | None}}.
It is used by tests/test_tartur_wiring_dmm.py and, pointed at a baseline checkout, to prove toggle-off output is unchanged.
"""
import contextlib
import importlib
import importlib.util
import math
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

_TK = ('tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog', 'tkinter.filedialog', 'tkinter.font', 'tkinter.scrolledtext')
FIXED = datetime(2026, 1, 2, 3, 4, 5)


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED


def stub_tk():
    try:
        import tkinter  # noqa: F401
    except Exception:
        for n in _TK:
            sys.modules.setdefault(n, mock.MagicMock())


class Var:
    def __init__(self, v=''):
        self.v = v

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


ENGINES = ('truevolt:34461A', 'truevolt:34470A', 'dacq:34970A', 'agilent34401a', 'fluke8846a',
           'handheld:Fluke 115', 'handheld:Fluke 87V', 'handheld:Klein MM325', 'handheld:Fluke 287')


def _load_path(root, rel, name):
    spec = importlib.util.spec_from_file_location(name, Path(root) / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fresh(root):
    """Forget every module of another source tree and put `root` first on the path."""
    for name in list(sys.modules):
        mod = sys.modules[name]
        f = getattr(mod, '__file__', None) or ''
        if name in ('report_pdf', 'report_dialog', 'tartur', 'tartur_wiring', 'uncertainty', 'uncertainty_budget', 'specmanager', 'labregistry',
                    'procspec', 'datamode', 'ui_theme', 'ui_shell', 'appdata', 'drivers', 'hookups', 'branding', 'suite_info',
                    'truevolt_verification', 'dacq_verification', 'handheld_dmm') or name.startswith('drivers.') \
                or (f and str(Path(f).resolve()).startswith(str(Path(root).resolve())) and name not in ('__main__',)):
            sys.modules.pop(name, None)
    sys.path[:] = [str(Path(root)), str(Path(root) / 'Procedures')] + [p for p in sys.path if Path(p).resolve() not in (Path(root).resolve(), Path(root).resolve() / 'Procedures')]
    sys.path[:] = [p for p in sys.path if 'scratchpad/wt-' not in p or Path(p).resolve() in (Path(root).resolve(), Path(root).resolve() / 'Procedures')]


def _app_class(mod):
    return mod.App


def _record_point_row(app, POINTS, jitter=0.38):
    """What the engine's --demo branch records for the point_row engines: nominal + error * sin(id * 1.71) * 0.38."""
    for p in POINTS:
        reading = p['nominal'] + p.get('error', 0) * math.sin(p['id'] * 1.71) * jitter if 'error' in p else (p['low'] + p['high']) / 2
        lim = p.get('error')
        if lim is None:
            lim = (p['high'] - p['low']) / 2
            reading = (p['low'] + p['high']) / 2 + lim * math.sin(p['id'] * 1.71) * jitter
        fail = (abs(reading - p['nominal']) > lim) if 'error' in p else not (p['low'] <= reading <= p['high'])
        rec = dict(reading=reading, result='FAIL' if fail else 'PASS', synthetic=True, timestamp=FIXED.isoformat(timespec='seconds'), data='As Found')
        app.found[str(p['id'])] = rec
    # a few points measured again as As Left
    for p in POINTS[::37]:
        rec = dict(app.found[str(p['id'])], data='As Left')
        app.left[str(p['id'])] = rec


def _setup_point_row(mod, app, POINTS):
    app.asset, app.serial, app.demo = Var('A-TEST'), Var('SN1'), True
    app.status = Var()
    app.root = mock.MagicMock()
    _record_point_row(app, POINTS)


def build_engine(spec, root):
    """-> (app, module, points).  spec like 'truevolt:34461A'."""
    kind, _, arg = spec.partition(':')
    if kind == 'truevolt':
        mod = importlib.import_module('truevolt_verification')
        mod.configure(arg)
        app = object.__new__(mod.App)
        _setup_point_row(mod, app, mod.POINTS)
        app.period = Var('1 year')
        app.include_optional = Var(True)
        return app, mod, mod.POINTS
    if kind == 'dacq':
        mod = importlib.import_module('dacq_verification')
        mod.configure(arg)
        app = object.__new__(mod.App)
        _setup_point_row(mod, app, mod.POINTS)
        app.period = Var('1 year')
        app.cal_model = Var(next(iter(mod.CALIBRATORS)))
        return app, mod, mod.POINTS
    if kind in ('agilent34401a', 'fluke8846a'):
        mod = importlib.import_module('Agilent_34401A' if kind == 'agilent34401a' else 'Fluke_8846A_Verification')
        app = object.__new__(mod.App)
        _setup_point_row(mod, app, mod.POINTS)
        app.results = app.found
        return app, mod, mod.POINTS
    if kind == 'handheld':
        mod = importlib.import_module('handheld_dmm')
        spec_file = {'Fluke 115': None, 'Fluke 87V': 'fluke_87v_pv.json', 'Klein MM325': 'klein_mm325_pv.json', 'Fluke 287': 'fluke_287_289_pv.json'}[arg]
        model = {'Fluke 115': '115', 'Fluke 87V': '87V', 'Klein MM325': 'MM325', 'Fluke 287': '287'}[arg]
        spec = mod.load_spec(Path(root) / 'specs' / spec_file) if spec_file else mod.load_spec()
        app = object.__new__(mod.App)
        app.model, app.demo, app.spec = model, True, spec
        app.info = spec['models'][model]
        app.points = mod.points_for(spec, model)
        app.asset, app.serial, app.status = Var('A-TEST'), Var('SN1'), Var()
        app.ir = False
        app.cal_mode = Var('Fluke 5522A' if arg == 'Fluke 87V' else 'Fluke 5560A')
        app.root = mock.MagicMock()
        app._update_row = lambda p: None
        app.save = lambda silent=False: None
        for p in app.points:
            app._record_demo(p)
        for p in app.points[::29]:
            app.left[str(p['id'])] = dict(app.results[p['id']] if p['id'] in app.results else app.found[str(p['id'])], data='As Left')
        return app, mod, app.points
    raise KeyError(spec)


def dump(root, outdir, show, specs=ENGINES, home=None):
    """Run every engine's real export code from the tree `root`.  show: the TAR / TUR choice (None = key absent, as before the feature)."""
    stub_tk()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    home = Path(home or outdir / 'home')
    (home / '.calibration_suite').mkdir(parents=True, exist_ok=True)
    (home / '.calibration_suite' / 'report_tartur.json').write_text('{"show_tar_tur": %s}' % ('true' if show else 'false'))
    old_home = os.environ.get('HOME')
    os.environ['HOME'] = str(home)
    os.environ.setdefault('CALSUITE_DATA', str(outdir / 'data'))
    import reportlab.rl_config as rc
    rc.invariant = 1
    out = {}
    try:
        for spec in specs:
            _fresh(root)
            app, mod, points = build_engine(spec, root)
            tag = spec.replace(':', '_').replace(' ', '_')
            pdf, csvp = outdir / f'{tag}.pdf', outdir / f'{tag}.csv'
            import report_dialog
            import report_pdf
            details = {'technician': 'T', 'temperature': '23', 'humidity': '40', 'standards': []}
            if show is not None:
                details['show_tar_tur'] = bool(show)
            names = [n for n in ('filedialog', 'messagebox') if hasattr(mod, n)]
            with contextlib.ExitStack() as st:
                st.enter_context(mock.patch.object(report_dialog, 'ask_details', lambda *a, **k: dict(details)))
                st.enter_context(mock.patch.object(report_pdf, 'datetime', _Clock))
                st.enter_context(mock.patch.object(mod.filedialog, 'asksaveasfilename', lambda **k: str(pdf)))
                for n in names:
                    pass
                mod.ui.report_filename  # attribute exists
                app.export_pdf()
                res = {'pdf': pdf, 'csv': None}
                if hasattr(app, 'export'):
                    st.enter_context(mock.patch.object(mod.filedialog, 'asksaveasfilename', lambda **k: str(csvp)))
                    app.export()
                    res['csv'] = csvp
            res['rows'] = app.certificate_rows()
            out[spec] = res
    finally:
        if old_home is None:
            os.environ.pop('HOME', None)
        else:
            os.environ['HOME'] = old_home
    return out


if __name__ == '__main__':
    root, outdir, show = sys.argv[1], sys.argv[2], {'on': True, 'off': False, 'none': None}[sys.argv[3]]
    r = dump(root, outdir, show)
    for k, v in r.items():
        print(k, len(v['rows']), v['pdf'].stat().st_size, v['csv'] and v['csv'].stat().st_size)
