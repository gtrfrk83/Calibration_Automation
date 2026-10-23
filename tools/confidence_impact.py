"""Impact of the 5522A confidence level (99 %, divisor 2.576 instead of 2) on the reported uncertainty and TUR of every multimeter procedure.

Read-only analysis: it builds a throw-away lab_registry database in a temp folder (CALSUITE_DATA), runs the real report arithmetic
(report_pdf.point_uncertainty / tartur.compute, the same functions the PDF export uses) once with the old divisor (2.0 forced) and once with the
shipped sheet (99 %, 2.576), for the points each procedure would print with the 5522A as the calibrator, and prints old / new / change.
Usage:  python tools/confidence_impact.py [--all]       (no instruments, no tkinter needed)
"""
import math
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'Procedures')]
os.environ['CALSUITE_DATA'] = tempfile.mkdtemp()
os.environ['HOME'] = os.environ['CALSUITE_DATA']
import _tk_stub  # noqa: E402
_tk_stub.install()
import specmanager as sm  # noqa: E402
import report_pdf  # noqa: E402
import tartur  # noqa: E402
import uncertainty  # noqa: E402

sm.seed()
STD = sm.standard('5522A')


def set_old():
    sm.set_standard_field(STD.id, 'divisor', 2.0, who='impact', reason='simulate the old divisor')


def set_new():
    sm.set_standard_field(STD.id, 'divisor', None, who='impact', reason='shipped sheet level')


def engines():
    """name -> (list of (label, report point dict, low, high), calibrator model)."""
    import handheld_dmm as h
    out = {}

    def handheld(file, model, name):
        spec = h.load_spec(ROOT / 'specs' / file) if file else h.load_spec()
        app = object.__new__(h.App)
        app.model, app.spec = model, spec
        pts = []
        for p in h.points_for(spec, model):
            if p.get('test') != 'numeric' or not h.App.has_uncertainty(p):
                continue
            f = Decimal(str(p['factor']))
            clean = lambda d: float(f'{float(d * f):.9g}')
            q = dict(kind='OHM2' if p['kind'] == 'OHM' else p['kind'], nominal=p['applied']['value'], frequency=p['applied'].get('frequency'),
                     unit=p['base_unit'], range=None)
            pts.append((f"{p['id']} {p['section']} {p['range']} {p['applied']['value']:g}{p['base_unit']}"
                        + (f" @ {p['applied']['frequency']:g} Hz" if p['applied'].get('frequency') else ''), q, clean(Decimal(p['low'])), clean(Decimal(p['high']))))
        out[name] = pts

    handheld(None, '117', 'Fluke 117 (110 series)')
    handheld('fluke_87v_pv.json', '87V', 'Fluke 87V')
    import agilent34410a_verification as A
    out['Keysight 34410A'] = [(f"{p['id']} {p['kind']} {p['nominal']:g} {p['unit']}" + (f" @ {p['frequency']:g} Hz" if p.get('frequency') else ''), p,
                               *__import__('tartur_wiring').point_limits(p)) for p in A.POINTS if p['source'] == 'calibrator']
    import fluke8808a_verification as E
    E.configure()
    out['Fluke 8808A'] = [(f"{p['ref']} {p['kind']} {p['nominal']:g} {p['unit']}" + (f" @ {p['frequency']:g} Hz" if p.get('frequency') else ''), p,
                           *__import__('tartur_wiring').point_limits(p)) for p in E.POINTS if p.get('source') != 'none']
    return out


def figures(p, low, high, std):
    unc = tartur.compute(p, low, high, standard=std)
    return unc['uncertainty'], unc['tur'], unc['tar']


def main(show_all=False):
    eng = engines()
    rows = {}
    for state in ('old', 'new'):
        (set_old if state == 'old' else set_new)()
        for name, pts in eng.items():
            for label, p, lo, hi in pts:
                rows.setdefault((name, label), {})[state] = figures(p, lo, hi, '5522A')
    print(f"5522A divisor: old 2.0 -> new {sm.standard('5522A').divisor()[0]}")
    for name in eng:
        pts = [(k[1], v) for k, v in rows.items() if k[0] == name and v['old'][0] and v['new'][0]]
        ch = [(l, v) for l, v in pts if v['new'][0] != v['old'][0]]
        print(f"\n== {name}: {len(pts)} points with an uncertainty, {len(ch)} change ({len(pts) - len(ch)} stay at the CMC floor)")
        for l, v in (pts if show_all else ch[:0]):
            pass
        shown = pts if show_all else ch
        for l, v in shown:
            (uo, to, _), (un, tn, _) = v['old'], v['new']
            print(f"  {l:60s} U {uo:.4g} -> {un:.4g} ({(un / uo - 1) * 100:+.1f} %)   TUR {to:.4g} -> {tn:.4g} ({(tn / to - 1) * 100:+.1f} %)")
        if ch:
            r = [v['new'][0] / v['old'][0] for _, v in ch]
            print(f"  changed points: U ratio min {min(r):.4f} max {max(r):.4f}  (2/2.576 = {2 / 2.576:.4f})")


if __name__ == '__main__':
    main('--all' in sys.argv)
