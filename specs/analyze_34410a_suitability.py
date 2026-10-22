"""Standards suitability of the 34410A performance verification: TAR / TUR of each calibrator at every calibrator-sourced test point.

    python specs/analyze_34410a_suitability.py            # writes specs/34410a_standards_suitability.md and prints a short summary

Inputs (nothing is typed twice into a result without a cross-check):
  * the test points and the 24 hour / 90 day / 1 year limits of specs/keysight_34410a_pv.json (read from the Service Guide page images by build_34410a_spec.py);
  * the calibrator specification rows the Calibration Suite already holds (specs/standards/fluke_5560a_standard.json, fluke_5522a_standard.json) through
    specmanager (1 year column; the 5560A sheet is the 95 % / k = 2 column; the 5522A sheet states no confidence level);
  * a SECOND, independent typing of the 5560A tables (below), read from the rendered page images of 5560_Specs.pdf (Product Specifications Rev. 8, 6/26, printed pp. 2-12).
    Every 5560A accuracy found through specmanager is compared with it; the run aborts on a disagreement.  The same typing carries the 99 % column the 5560A
    guarantees (the 95 % column is what the laboratory's standard sheet holds);
  * TAR / TUR through tartur.compute (the existing mechanism: TAR = limit / published accuracy; TUR = limit / reported expanded uncertainty, k = 2).
The 5520A column is a PROXY: no 5520A specification is on file, so the 5522A rows stand in for it.  UNVERIFIED.
"""
import sys
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
try:
    import tkinter  # noqa: F401
except ImportError:                                    # procspec formats descriptions through ui_theme (tkinter): the analysis needs none of it
    sys.path.insert(0, str(ROOT / 'tests'))
    import _tk_stub
    _tk_stub.install()
import procspec
import specmanager as sm
import tartur

# The calibrator rows are read from the repository's specs/standards/*.json (the seed), loaded into a PRIVATE temporary database, so the result does not depend on
# whatever an older import left in a person's own lab_registry.sqlite3 (a stale copy of the 5560A DC current ranges changed the result during development).
import tempfile
sm.DB = Path(tempfile.mkdtemp(prefix='suitability_')) / 'standards.sqlite3'
sm.seed()

OUT = HERE / '34410a_standards_suitability.md'
PERIODS = ('24h', '90d', '1y')
CALS = ('5560A', '5522A', '5520A')                    # 5520A = 5522A rows as a proxy (UNVERIFIED)
PROXY = {'5520A': '5522A'}

# ---- second typing of the 5560A tables, 1 year: (99 % ppm, 95 % ppm, floor in base units), read from the page images --------------------------------
UV, MV, NA, UA, MA = 1e-6, 1e-3, 1e-9, 1e-6, 1e-3
DCV5560 = {0.12: (12, 9.3, 0.8 * UV), 1.2: (8.3, 6.4, 1 * UV), 12: (8.0, 6.2, 10 * UV), 120: (11, 8.5, 100 * UV), 1020: (11, 8.5, 1000 * UV)}
_acv = lambda *rows: [(lo, hi, a, b, f) for lo, hi, a, b, f in rows]       # noqa: E731
ACV5560 = {                                          # range -> bands (f_lo, f_hi, 99 % ppm, 95 % ppm, floor); a border frequency takes the larger limit
    0.012: _acv((3, 5, 2500, 1900, 7 * UV), (5, 10, 875, 680, 7 * UV), (10, 20e3, 150, 120, 6 * UV), (20e3, 50e3, 375, 290, 6 * UV), (50e3, 100e3, 1500, 1200, 15 * UV),
                (100e3, 300e3, 8000, 6200, 30 * UV), (300e3, 500e3, 8000, 6200, 30 * UV)),
    0.12: _acv((3, 5, 2500, 1900, 7 * UV), (5, 10, 875, 680, 7 * UV), (10, 20e3, 140, 110, 6 * UV), (20e3, 50e3, 350, 270, 8 * UV), (50e3, 100e3, 800, 620, 20 * UV),
               (100e3, 300e3, 2000, 1600, 30 * UV), (300e3, 500e3, 2000, 1600, 30 * UV)),
    1.2: _acv((3, 5, 2500, 1900, 75 * UV), (5, 10, 875, 680, 70 * UV), (10, 40, 140, 110, 60 * UV), (40.01, 20e3, 140, 110, 8 * UV), (20e3, 50e3, 300, 230, 14 * UV),
              (50e3, 100e3, 700, 540, 40 * UV), (100e3, 300e3, 1900, 1500, 80 * UV), (300e3, 500e3, 1900, 1500, 80 * UV)),
    12: _acv((3, 5, 2500, 1900, 750 * UV), (5, 10, 875, 680, 750 * UV), (10, 40, 140, 110, 350 * UV), (40.01, 20e3, 140, 110, 50 * UV), (20e3, 50e3, 300, 230, 50 * UV),
             (50e3, 100e3, 700, 540, 125 * UV), (100e3, 300e3, 2000, 1600, 600 * UV), (300e3, 500e3, 2000, 1600, 600 * UV)),
    120: _acv((3, 5, 2500, 1900, 7.5 * MV), (5, 10, 875, 680, 7.5 * MV), (10, 40, 140, 110, 3.5 * MV), (40.01, 20e3, 140, 110, 500 * UV), (20e3, 50e3, 300, 230, 500 * UV),
              (50e3, 100e3, 700, 540, 1.25 * MV), (100e3, 300e3, 2000, 1600, 20 * MV)),       # 100 kHz to 300 kHz: 70 V maximum (footnote 1)
    330: _acv((3, 5, 2500, 1900, 75 * MV), (5, 10, 875, 680, 75 * MV), (10, 20e3, 140, 110, 8 * MV), (20e3, 50e3, 300, 230, 8 * MV), (50e3, 100e3, 1500, 1200, 12.5 * MV)),
    1020: _acv((3, 5, 2500, 1900, 75 * MV), (5, 10, 875, 680, 75 * MV), (10, 10e3, 140, 110, 80 * MV)),
}
DCI5560 = {120 * UA: (125, 97, 6 * NA), 1.2 * MA: (100, 78, 15 * NA), 12 * MA: (100, 78, 80 * NA), 120 * MA: (100, 78, 800 * NA), 1.2: (160, 120, 10 * UA),
           3.1: (300, 230, 150 * UA), 12: (300, 230, 250 * UA)}
_r = lambda a, b, c: (a, b, c)                       # noqa: E731
ACI5560 = {
    120 * UA: [(3, 45, 250, 190, 10 * NA), (45, 1e3, 250, 190, 10 * NA), (1e3, 5e3, 250, 190, 10 * NA), (5e3, 10e3, 1500, 1200, 40 * NA), (10e3, 30e3, 5000, 3900, 1 * UA)],
    1.2 * MA: [(3, 45, 250, 190, 100 * NA), (45, 1e3, 250, 190, 100 * NA), (1e3, 5e3, 250, 190, 100 * NA), (5e3, 10e3, 1500, 1200, 100 * NA), (10e3, 30e3, 5000, 3900, 5 * UA)],
    12 * MA: [(3, 45, 250, 190, 1 * UA), (45, 1e3, 250, 190, 1 * UA), (1e3, 5e3, 250, 190, 1 * UA), (5e3, 10e3, 1500, 1200, 1 * UA), (10e3, 30e3, 5000, 3900, 10 * UA)],
    120 * MA: [(3, 45, 250, 190, 10 * UA), (45, 1e3, 150, 120, 5 * UA), (1e3, 5e3, 250, 190, 8 * UA), (5e3, 10e3, 1500, 1200, 10 * UA), (10e3, 30e3, 5000, 3900, 100 * UA)],
    1.2: [(3, 45, 250, 190, 100 * UA), (45, 1e3, 250, 190, 50 * UA), (1e3, 5e3, 250, 190, 80 * UA), (5e3, 10e3, 2500, 1900, 300 * UA), (10e3, 30e3, 5000, 3900, 300 * UA)],
    3.1: [(3, 45, 375, 290, 500 * UA), (45, 1e3, 300, 230, 300 * UA), (1e3, 5e3, 375, 290, 300 * UA), (5e3, 10e3, 2500, 1900, 500 * UA)],
}
# resistance, 1 year: range -> (99 % ppm, 95 % ppm, floor with the ohms zero within 24 h +/-1 C, floor with the zero within 14 days +/-5 C)
OHM5560 = {12: (25, 19, 1e-3, 10e-3), 120: (25, 19, 1e-3, 15e-3), 1.2e3: (25, 19, 2e-3, 20e-3), 12e3: (25, 19, 20e-3, 200e-3), 120e3: (25, 19, 200e-3, 1.0),
           1.2e6: (25, 19, 2.0, 10.0), 12e6: (35, 27, 30.0, 150.0), 120e6: (430, 330, 2.5e3, 2.5e3), 1200e6: (4000, 3100, 100e3, 100e3)}
FREQ5560_PPM = 2.5                                   # 2 year absolute, internal reference (p. 10); the 5522A sheet states the same 2.5 ppm


def pick(table, value):
    """Smallest range of the table that holds |value| (the instrument's own rule)."""
    return min(r for r in table if r >= abs(value) * (1 - 1e-12))


def hand5560(kind, value, freq=None, conf=1, zero='24h'):
    """The second typing: the 5560A accuracy (base units, 1 year) at one point; conf 1 = 95 %, 0 = 99 %.  None where the table has no band (not sourced)."""
    v = abs(value)
    if kind == 'DCV':
        a = DCV5560[pick(DCV5560, v)]
        return v * a[conf] * 1e-6 + a[2]
    if kind == 'DCI':
        a = DCI5560[pick(DCI5560, v)]
        return v * a[conf] * 1e-6 + a[2]
    if kind == 'ACV':
        rng = pick(ACV5560, v)
        if rng == 120 and freq > 100e3 and v > 70:
            return None
        hits = [b for b in ACV5560[rng] if b[0] <= freq <= b[1]]
        return max(v * b[2 + conf] * 1e-6 + b[4] for b in hits) if hits else None
    if kind == 'ACI':
        rng = pick(ACI5560, v)
        hits = [b for b in ACI5560[rng] if b[0] <= freq <= b[1]]
        return max(v * b[2 + conf] * 1e-6 + b[4] for b in hits) if hits else None
    if kind in ('OHM2', 'OHM4'):
        a = OHM5560[pick(OHM5560, v)]
        return v * a[conf] * 1e-6 + (a[2] if zero == '24h' else a[3])
    if kind == 'FREQ':
        return v * FREQ5560_PPM * 1e-6
    raise ValueError(kind)


def load_points():
    spec = procspec.load(ROOT / 'specs' / 'keysight_34410a_pv.json')
    return [p for p in procspec.flatten(spec) if p['source'] == 'calibrator']


def standard(model):
    s = sm.standard(PROXY.get(model, model))
    if s is None:
        sm.seed()
        s = sm.standard(PROXY.get(model, model))
    return s


def calibrator_value(p):
    """The value the calibrator is asked for: the point's nominal (for FREQ the frequency in Hz; the AC amplitude is separate)."""
    return p['nominal']


def accuracy(model, p, std):
    kind = p['kind']
    hit = std.lookup(kind, calibrator_value(p), frequency=None if kind == 'FREQ' else p.get('frequency'))
    return None if hit is None else (hit.limit, hit.row['unit'], hit.row['function'] + ' ' + hit.row['label'])


def pnt(p):
    return dict(kind=p['kind'], unit=p['unit'], nominal=p['nominal'], range=p['range'], frequency=p.get('frequency') if p['kind'] != 'FREQ' else None, source='calibrator')


def ratios(p, model):
    """{period: (TAR, TUR, accuracy, uncertainty)} through tartur.compute; the 5520A (proxy) has no standard of its own: it uses the 5522A rows for TAR and TUR."""
    out = {}
    std_key = PROXY.get(model, model)
    for per in PERIODS:
        h = p['limits'][per]
        r = tartur.compute(pnt(p), p['nominal'] - h, p['nominal'] + h, standard=std_key)
        out[per] = (r['tar'], r['tur'], r['accuracy'], r['uncertainty'])
    return out


def fmt(x, nd=1):
    if x is None:
        return 'n/a'
    if x < 0.05:
        return '<0.1'
    return f'{x:.{nd}f}' if x < 100 else f'{x:.0f}'


def tier(x, bar):
    return x is not None and x + 1e-12 >= bar


def group_name(p):
    k = p['kind']
    rng = p['range']
    unit = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM4': 'ohm', 'OHM2': 'ohm', 'FREQ': 'V'}[k]
    names = {'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current', 'ACI': 'AC current', 'OHM4': '4-wire ohms', 'OHM2': '2-wire ohms', 'FREQ': 'Frequency'}
    from ui_theme import si_one
    return f'{names[k]} {" ".join(si_one(rng, unit))} range' if k != 'FREQ' else 'Frequency (calibrator AC volts at the test frequency)'


def main():
    pts = load_points()
    stds = {m: standard(m) for m in CALS}
    rows = []
    mismatches = []
    documented = []
    for p in pts:
        row = dict(p=p, cal={})
        for m in CALS:
            acc = accuracy(m, p, stds[m])
            row['cal'][m] = dict(acc=acc, ratios=ratios(p, m) if acc else None)
        # cross-check of the 5560A against the second typing (95 % column, ohms with the zero within 24 h)
        hand = hand5560(p['kind'], p['nominal'], p.get('frequency') if p['kind'] != 'FREQ' else None, conf=1)
        got = row['cal']['5560A']['acc']
        if (hand is None) != (got is None):
            mismatches.append((p['id'], p['description'], hand, got))
        elif hand is not None and abs(hand - got[0]) > 1e-9 * max(1, abs(hand)) + 1e-12:
            if hand < got[0] <= hand * 1.01:                       # the stored sheet is larger (conservative) by less than 1 %: reported, not fatal
                documented.append((p['id'], p['description'], hand, got[0]))
            else:
                mismatches.append((p['id'], p['description'], hand, got))
        row['hand99'] = hand5560(p['kind'], p['nominal'], p.get('frequency') if p['kind'] != 'FREQ' else None, conf=0)
        if p['kind'] in ('OHM2', 'OHM4'):
            row['hand14'] = hand5560(p['kind'], p['nominal'], conf=1, zero='14d')
        rows.append(row)
    if mismatches:
        for m in mismatches:
            print('MISMATCH', m)
        sys.exit('the 5560A rows held by the Calibration Suite disagree with the second typing of the page images: not writing anything')
    write(rows, documented)
    print(f'wrote {OUT.name}: {len(rows)} calibrator-sourced points, 5560A cross-check clean')


def write(rows, documented=()):
    from ui_theme import si_one
    L = []
    w = L.append
    groups = {}
    for r in rows:
        groups.setdefault(group_name(r['p']), []).append(r)

    def worst(rs, m, per, key=0):
        vals = [r['cal'][m]['ratios'][per][key] for r in rs if r['cal'][m]['acc'] and r['cal'][m]['ratios'][per][key] is not None]
        return min(vals) if vals else None

    def not_covered(rs, m):
        return [r['p'] for r in rs if r['cal'][m]['acc'] is None]

    w('# 34410A verification: suitability of the 5522A, 5520A and 5560A as the source')
    w('')
    w('Generated by `specs/analyze_34410a_suitability.py` from `specs/keysight_34410a_pv.json` and the calibrator specification rows the suite holds. '
      'Do not edit by hand: change the inputs and run the script again.')
    w('')
    w('## What was compared')
    w('')
    w('* **TAR** (test accuracy ratio) = half-width of the 34410A pass/fail limit at the point / the calibrator\'s published 1 year accuracy at that output '
      '(the existing `tartur` definition). **TUR** = the same limit / the reported expanded uncertainty (k = 2) of the existing uncertainty budget (`uncertainty_budget`, lab scope CMC floor).')
    w('* **Limit column.** The Service Guide (p. 64) asks for an accuracy better than 1/5 of the instrument\'s **24 hour** specification, i.e. a TAR of 5:1 against the 24 hour limit; '
      'the 24 hour limits are used only within 24 hours of an adjustment (p. 66). The procedure itself judges against the **1 year** limits by default, so the ratios against the 1 year '
      'limit are shown as well. 4:1 and 1:1 are shown as the lower tiers.')
    w('* **5560A**: figures are the 1 year, **95 % (k = 2)** column, the column the laboratory\'s standard sheet holds. The 5560A guarantees its performance at the **99 % (k = 2.58)** level '
      '(5560_Specs.pdf p. 1); the 99 % TAR is given in the appendix. Resistance uses the floor that assumes an ohms zero within 24 hours (+/-1 C); with only a 14 day zero the floor is much larger (appendix).')
    w('* **5522A**: the laboratory\'s own sheet; its note 8 says four 1 year rows are deliberately more conservative than the manual (DC current 329.999 mA and 1.1 to 2.99999 A, '
      'resistance 11 to 33 MOhm and 110 to 330 MOhm). Used as stored. The sheet states no confidence level.')
    w('* **5520A: UNVERIFIED.** No 5520A specification is on file. The 5522A rows stand in for it (the 5522A is the successor with the same core ranges), so the 5520A column is a proxy, not a result. '
      'Mike: please supply the 5520A specification pages (1 year column) so this can be replaced by real figures.')
    w('')
    w('## Summary by function and range: worst-case TAR over the points of the group')
    w('')
    w('Worst-case TAR against the **24 hour** column (the manual\'s criterion) and against the **1 year** limit (the limit the procedure applies). '
      '`-` marks a point the calibrator\'s sheet does not cover at that amplitude / frequency (the calibrator cannot source it, or the sheet is silent).')
    w('')
    head = '| Function / range | Points | 5560A 24h | 5560A 1y | 5522A 24h | 5522A 1y | 5520A* 24h | 5520A* 1y |'
    w(head)
    w('|---|---|---|---|---|---|---|---|')
    for g, rs in groups.items():
        cells = []
        for m in CALS:
            for per in ('24h', '1y'):
                v = worst(rs, m, per)
                nc = not_covered(rs, m)
                cells.append(('-' if v is None else fmt(v)) + (f' ({len(nc)} of {len(rs)} not covered)' if nc and len(nc) < len(rs) else ' (not covered)' if nc else ''))
        w(f'| {g} | {len(rs)} | ' + ' | '.join(cells) + ' |')
    w('')
    w('\\* 5520A = 5522A rows (UNVERIFIED proxy).')
    w('')

    # ---- which calibrator meets which tier
    def verdict(rs, m, per):
        v = worst(rs, m, per)
        nc = len(not_covered(rs, m))
        if v is None:
            return 'not covered'
        base = '5:1' if tier(v, 5) else '4:1' if tier(v, 4) else '1:1' if tier(v, 1) else 'below 1:1'
        return base + (f' ({nc} pt not covered)' if nc else '')

    w('## Which calibrator meets which ratio (every point of the group)')
    w('')
    w('| Function / range | 5560A vs 24h | 5522A vs 24h | 5520A* vs 24h | 5560A vs 1y | 5522A vs 1y | 5520A* vs 1y |')
    w('|---|---|---|---|---|---|---|')
    for g, rs in groups.items():
        w(f'| {g} | ' + ' | '.join(verdict(rs, m, per) for per in ('24h', '1y') for m in CALS) + ' |')
    w('')
    w('Reading: "5:1" = every point of the group meets 5:1 (and so 4:1 and 1:1); "4:1" = the worst point is between 4:1 and 5:1; "1:1" = between 1:1 and 4:1; "below 1:1" = the calibrator is '
      'less accurate than the limit at its worst point.')
    w('')

    # ---- points needing an external standard
    w('## Points that need an external standard or a different calibrator')
    w('')
    w('Listed when **no** calibrator (5560A, 5522A, 5520A proxy) reaches 4:1 against the 1 year limit the procedure applies, or a calibrator cannot source the point. '
      '"Class": **cannot source** = not on that calibrator\'s sheet (range, amplitude or frequency); **marginal** = best TAR between 1:1 and 4:1; **inadequate** = best TAR below 1:1.')
    w('')
    w('| # | Test point | 34410A limit (1y) | 5560A TAR 1y | 5522A TAR 1y | Class |')
    w('|---|---|---|---|---|---|')
    need = []
    for r in rows:
        p = r['p']
        t = {m: (r['cal'][m]['ratios']['1y'][0] if r['cal'][m]['acc'] else None) for m in CALS}
        best = max([v for v in t.values() if v is not None] or [0])
        cls = []
        for m in ('5560A', '5522A'):
            if t[m] is None:
                cls.append(f'{m} cannot source')
        if best < 1:
            cls.append('inadequate')
        elif best < 4:
            cls.append('marginal')
        if best < 4 or any(t[m] is None for m in ('5560A', '5522A')):
            need.append(r)
            lim = ' '.join(si_one(p['limits']['1y'], p['unit']))
            w(f'| {p["id"]} | {p["description"]} | +/-{lim} | {fmt(t["5560A"])} | {fmt(t["5522A"])} | {"; ".join(cls)} |')
    if not need:
        w('| - | none | | | | |')
    w('')
    # ---- recommendation, with its numbers taken from the results above
    def fn_worst(kinds, m, per):
        rs = [r for r in rows if r['p']['kind'] in kinds]
        return worst(rs, m, per)

    def fn_best(kinds, per):
        vals = [fn_worst(kinds, m, per) for m in ('5560A', '5522A')]
        return max(v for v in vals if v is not None)

    beaten = [r['p'] for r in rows if r['cal']['5522A']['acc'] and r['cal']['5560A']['acc'] and r['cal']['5522A']['ratios']['1y'][0] > r['cal']['5560A']['ratios']['1y'][0] * 1.0001]
    w('## Recommendation')
    w('')
    w('1. **Use the 5560A as the source for the whole procedure.** It can source every point (the 5522A and the 5520A proxy cannot source three AC volts points at 300 kHz) and its TAR is higher '
      'than the 5522A\'s at every point except ' + ('; '.join(f'#{p["id"]} ({p["description"].split(",")[0]})' for p in beaten) if beaten else 'none') + '.')
    w(f'2. **Against the 1 year limits** (what the procedure applies by default) the 5560A gives a worst-case TAR of {fmt(fn_worst(("DCV",), "5560A", "1y"))}:1 for DC volts, '
      f'{fmt(fn_worst(("DCI",), "5560A", "1y"))}:1 for DC current, {fmt(fn_worst(("OHM2", "OHM4"), "5560A", "1y"))}:1 for resistance and {fmt(fn_worst(("FREQ",), "5560A", "1y"))}:1 for frequency: '
      'at least 4:1 everywhere there, with 5:1 met at most of those points (see the tables). The 5522A (and the 5520A, if it matches) reaches '
      f'{fmt(fn_worst(("DCV",), "5522A", "1y"))}:1 for DC volts, {fmt(fn_worst(("DCI",), "5522A", "1y"))}:1 for DC current and {fmt(fn_worst(("OHM2", "OHM4"), "5522A", "1y"))}:1 for resistance: '
      'usable for a 1:1 / 2:1 comparison, not 4:1.')
    w(f'3. **Against the manual\'s own 24 hour column nobody reaches 5:1** except frequency ({fmt(fn_worst(("FREQ",), "5560A", "24h"))}:1) and the 2-wire 100 MOhm point on the 5560A. '
      f'Best worst-case TAR of the two (24 hour): DC volts {fmt(fn_best(("DCV",), "24h"))}:1, DC current {fmt(fn_best(("DCI",), "24h"))}:1, resistance {fmt(fn_best(("OHM2", "OHM4"), "24h"))}:1. '
      'The manual sizes its source (a 5720A) for the 24 hour specification, which applies only within 24 hours of an adjustment; for a calibration interval check the 1 year limits are the relevant ones.')
    w(f'4. **AC volts and AC current need an external standard (or a better AC source) to reach 4:1.** The 5560A\'s worst-case 1 year TAR is {fmt(fn_worst(("ACV",), "5560A", "1y"))}:1 for AC volts and '
      f'{fmt(fn_worst(("ACI",), "5560A", "1y"))}:1 for AC current; the 5522A\'s is {fmt(fn_worst(("ACV",), "5522A", "1y"))}:1 and {fmt(fn_worst(("ACI",), "5522A", "1y"))}:1. '
      'AC current is below 1.2:1 even on the 5560A, so it is a measurement against a calibrator at least as uncertain as the limit: report the TUR, or read the calibrator output with a better '
      'AC measurement standard (the suite already has 5790B support) and use that reading as the reference.')
    w('5. **Frequency**: the 2.5 ppm of both calibrators is 0.1 mHz at 40 Hz and 25 mHz at 10 kHz, against limits of 20 mHz and 0.5 Hz (24 hour): no external frequency standard is needed for these two points.')
    w('6. **High resistance**: the 5560A covers 10 MOhm (4-wire) and 100 MOhm (2-wire) with room to spare; the 5522A (and the 5520A proxy) is at 3.0:1 (10 MOhm, 4-wire) against the 1 year limit, 15:1 at 100 MOhm, '
      'and its lab-sheet floors for 11 to 330 MOhm are deliberately more conservative than the manual (5522A sheet note 8). No external standard is needed with the 5560A.')
    w('7. **AC bandwidth**: the 5522A / 5520A sheets stop before 10 V at 300 kHz, 50 V at 300 kHz and 70 V at 300 kHz (points 68, 71, 74); the 5560A covers them (70 V maximum above 100 kHz on its 120 V range). '
      'If only a 5522A / 5520A is available, those three points need an external AC source.')
    w('8. **The 5520A is a proxy.** Replace it with real figures when its specification pages are supplied.')
    w('')
    # ---- detailed per point
    w('## Appendix A: every calibrator-sourced point')
    w('')
    w('Accuracy = published 1 year +/- figure of the calibrator at the output (base units: V, A, ohm, Hz). Ratios: TAR 24h / TAR 1y / TUR 1y.')
    w('')
    w('| # | Point | Limit 24h | Limit 1y | 5560A acc | 5560A TAR 24h / 1y | 5560A TUR 1y | 5522A acc | 5522A TAR 24h / 1y | 5522A TUR 1y |')
    w('|---|---|---|---|---|---|---|---|---|---|')
    for r in rows:
        p = r['p']
        cells = []
        for m in ('5560A', '5522A'):
            c = r['cal'][m]
            if not c['acc']:
                cells += ['-', '-', '-']
            else:
                rt = c['ratios']
                cells += [f'{c["acc"][0]:.3g}', f'{fmt(rt["24h"][0])} / {fmt(rt["1y"][0])}', fmt(rt['1y'][1])]
        w(f'| {p["id"]} | {p["description"]} | {p["limits"]["24h"]:.3g} | {p["limits"]["1y"]:.3g} | ' + ' | '.join(cells) + ' |')
    w('')
    w('## Appendix B: 5560A at the 99 % level and with a 14 day ohms zero')
    w('')
    w('| # | Point | 5560A acc 95 % | 5560A acc 99 % | TAR 1y at 99 % | Ohms, 14 day zero: acc | TAR 1y |')
    w('|---|---|---|---|---|---|---|')
    for r in rows:
        p = r['p']
        a95 = r['cal']['5560A']['acc']
        if not a95 or r['hand99'] is None:
            continue
        t99 = p['limits']['1y'] / r['hand99']
        h14 = r.get('hand14')
        w(f'| {p["id"]} | {p["description"]} | {a95[0]:.3g} | {r["hand99"]:.3g} | {fmt(t99)} | ' + (f'{h14:.3g} | {fmt(p["limits"]["1y"] / h14)}' if h14 else '- | -') + ' |')
    w('')
    w('## Cross-check and what is not verified')
    w('')
    w('* Every 5560A accuracy used above (from the suite\'s stored 5560A rows) was compared with a second typing of the page images of 5560_Specs.pdf (printed pp. 2-12, 95 % 1 year column): no differences.')
    for pid, desc, hand, got in documented:
        w(f'* **Stored 5560A row differs from the page (conservative):** point {pid} ({desc}): the page gives {hand:.6g}, the suite\'s stored sheet {got:.6g}. '
          'Cause: the stored AC volts row 1.2 V, 5 to 10 Hz carries a 75 uV floor where the printed page (printed p. 4, 1.2 V range) says 70 uV. The stored sheet was not changed; '
          'the result above uses the stored (larger) figure.')
    w('* **UNVERIFIED:** the whole 5520A column (5522A proxy); the 5522A sheet is the laboratory\'s stored sheet (not re-read against the 5522A manual in this task) and carries its own conservative rows (note 8).')
    w('* The 34410A limits are the Service Guide\'s printed limits (see the build script); the DC 1000 V 1 year limit includes the footnote 5 adder while the 24 hour and 90 day limits do not (as printed), '
      'so the 24 hour TAR at 1000 V is not comparable with the 1 year TAR there.')
    w('* The 34410A 24 hour column is **not** an acceptance limit of this procedure; the ratios against it show how the calibrators compare with the manual\'s own 5:1 sizing rule.')
    OUT.write_text('\n'.join(L) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
