"""Golden snapshot of what the Datasheet Builder JUDGES with, for the 'Low / High limit' display change (tests/test_dsb_low_high_limits.py).

`snapshot(ds)` returns plain JSON data: for every period and every point the exact limit (low, high, minus, plus, source, one_sided), every step of the
runnable spec (so every low / high / display unit / padding / tol_text the run window and the report are built from) and the PASS / FAIL the handheld
engine gives to readings just below, on and just above each limit.  `golden()` shortens that to digests.  tests/dsb_golden_limits.json was written by
this module on the code BEFORE the display change (`python tests/dsb_golden.py <full.json> <golden.json>`); the test compares today's digests with it.
Test helper only."""
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import dsb_fixtures as fx  # noqa: E402
import datasheet_builder as db  # noqa: E402
import datasheet_builder_specs as dsp  # noqa: E402

D = Decimal


def sheets():
    """name -> Datasheet: the four sample sheets (symmetric), plus asymmetric, typed-limit and row-statement variants."""
    out = {'dmm_34461a_like': fx.dmm_34461a_like(), 'acv_bands': fx.acv_bands_sheet(), 'generator_33220a_like': fx.generator_33220a_like(),
           'scope_tds2000c_like': fx.scope_tds2000c_like()}
    # asymmetric: a different minus side in the function's table, and a point of its own with a different minus side
    asym = fx.dmm_34461a_like()
    f = asym.function('dcv')
    e = f.spec[0]
    e.exprs_minus = {per: db.parse_expr('0.01 % of reading + 0.01 % of range', 'V') for per in e.exprs}
    p = f.points[3]
    p.spec = db.SpecEntry({per: db.parse_expr('2 % of reading', 'V') for per in asym.period_ids()}, None, None, None,
                          {per: db.parse_expr('1 % of reading + 1 mV', 'V') for per in asym.period_ids()}, {per: '2 % of reading' for per in asym.period_ids()})
    out['dmm_asymmetric'] = asym
    # typed Low / High pairs (explicit asymmetric limits), on some points of one period only
    typed = fx.dmm_34461a_like()
    f = typed.function('dcv')
    for i, (lo, hi) in enumerate((('-0.0001', '0.0002'), ('4.9', '5.2'), ('9.95', '10.05'), ('2.5', '3.5'))):
        db.set_override(f, f.points[i + 1].id, '1y', lo, hi)
    g = typed.function('ohm2')
    db.set_override(g, g.points[0].id, '90d', '99.9', '100.3')
    out['dmm_typed_limits'] = typed
    # a row-level symmetric statement on points (what the grid writes), the second period following
    grid = fx.dmm_34461a_like()
    f = grid.function('dcv')
    for p in f.points[:6]:
        p.spec = db.SpecEntry({per: db.parse_expr('0.05 % of reading + 2 counts', 'V') for per in grid.period_ids()}, None, None, None, {},
                              {per: '0.05 % of reading + 2 counts' for per in grid.period_ids()})
    out['dmm_row_statements'] = grid
    rounded = fx.dmm_34461a_like()
    rounded.options['limit_rounding'] = 'outward'
    out['dmm_outward_rounding'] = rounded
    return out


def _s(x):
    return None if x is None else db.fmt(x)


def _judge(step, hh):
    """PASS / FAIL for readings around the limits, exactly as the engine's reading window judges them."""
    low, high = D(step['low']), D(step['high'])
    places = max(0, -low.as_tuple().exponent, -high.as_tuple().exponent)
    ulp = D(1).scaleb(-places)
    results = []
    for value in (low - ulp, low, (low + high) / 2, high, high + ulp):
        text = hh.pad_reading(step, format(value, 'f'))
        try:
            results.append([text, hh.judge_numeric(step, text)[0]])
        except ValueError as exc:
            results.append([text, 'ERR ' + str(exc)[:30]])
    return results


def snapshot(ds):
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as hh
    out = {'limits': {}, 'spec': {}, 'judged': {}, 'problems': []}
    for fn in ds.functions:
        for p in fn.points:
            for per in ds.period_ids():
                try:
                    lim = fn.limit_for(p, per, ds)
                except db.DsError as exc:
                    out['limits'][f'{fn.id}|{p.id}|{per}'] = 'ERR ' + exc.code
                    continue
                out['limits'][f'{fn.id}|{p.id}|{per}'] = [_s(lim.nominal), _s(lim.low), _s(lim.high), _s(lim.minus), _s(lim.plus), lim.source, lim.one_sided, lim.ambiguous]
    for per in ds.period_ids():
        res = dsp.export_spec(ds, per)
        out['problems'].append([str(x) for x in res.problems])
        if res.spec is None:
            out['judged'][per] = None
            continue
        # the steps are what the run window and the report are built from (the spec's 'dsb' block also embeds the datasheet, whose key order is not stable)
        out['spec'][per] = {'steps': res.spec['steps'], 'options': res.spec['options'], 'models': res.spec['models']}
        out['judged'][per] = {s['id']: _judge(s, hh) for s in res.spec['steps'] if s.get('test') == 'numeric'}
    return out


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()[:20]


def compact(snap):
    """The snapshot as short digests (one per section and period) plus counts: small enough to keep in the repository."""
    return {'points': len(snap['limits']), 'limits': digest(snap['limits']), 'problems': digest(snap['problems']),
            'spec': {per: [len(v['steps']), digest(v)] for per, v in snap['spec'].items()},
            'judged': {per: [len(v or {}), digest(v)] for per, v in snap['judged'].items()},
            'verdicts': {per: sum(1 for r in (v or {}).values() for x in r if x[1] == 'PASS') for per, v in snap['judged'].items()}}


def snapshot_all():
    return {name: snapshot(ds) for name, ds in sheets().items()}


def golden():
    """What tests/dsb_golden_limits.json holds: {sheet name: compact(snapshot)}."""
    return {name: compact(snap) for name, snap in snapshot_all().items()}


if __name__ == '__main__':
    full = snapshot_all()
    Path(sys.argv[1]).write_text(json.dumps(full, sort_keys=True, separators=(',', ':'), ensure_ascii=True), encoding='utf-8')
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps({n: compact(v) for n, v in full.items()}, sort_keys=True, indent=1, ensure_ascii=True) + '\n', encoding='utf-8')
