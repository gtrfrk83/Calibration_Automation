#!/usr/bin/env python3
"""Diff report for the Fluke 5560A standards sheet: the sheet before (git revision, default 794aeff) against the sheet built from the manufacturer's
document by specs/build_5560a_standard_from_manual.py.  Writes specs/fluke_5560a_spec_check.md.

What it does, in order
  1. matches every old row to the new rows (same kind, direction, variant, amplitude band, frequency band inside the old band) and compares the 1 yr
     figures (rel, fs_rel, fs_value, abs): confirmed / changed / removed; new rows not matched by an old row are 'added';
  2. builds two temporary lab_registry copies (old sheet, new sheet) with specmanager.seed and compares uncertainty_budget.build and tartur.compute for
     representative points, and for every capacitance / ACV / ACI / OHM point of the shipped *_pv.json catalogues that falls in a changed row;
  3. shows that the 90 day rows change nothing for 1 yr reports (default period stays 1 yr);
  4. runs the deployment test on a temporary database (seed over an existing sheet, then the manual Standards Specs Import).
It never opens lab_registry.sqlite3 or calibration_procedures.sqlite3 of the lab: every database it touches is a temporary file.

Run from the repository root:   python specs/analyze_5560a_spec_check.py [--old-rev 794aeff] [--out specs/fluke_5560a_spec_check.md]
"""
import argparse
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import specmanager as sm  # noqa: E402
import tartur  # noqa: E402
import uncertainty_budget as ub  # noqa: E402

NEW_PATH = os.path.join(HERE, 'specs', 'standards', 'fluke_5560a_standard.json')
OLD_REL = 'specs/standards/fluke_5560a_standard.json'
MODEL = '5560A'
DOC = 'Fluke 5560A Product Specifications, Dec 2022 Rev. 8, 6/26'
DEFAULT_OUT = os.path.join(HERE, 'specs', 'fluke_5560a_spec_check.md')


def load_old(rev):
    raw = subprocess.run(['git', 'show', f'{rev}:{OLD_REL}'], cwd=HERE, capture_output=True, check=True).stdout
    return json.loads(raw.decode('utf-8'))


def load_new():
    with open(NEW_PATH, encoding='utf-8') as fh:
        return json.load(fh)


def flat(d):
    return [(f, r) for f in d['functions'] for r in f['ranges']]


def close(a, b):
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-18)


def spec_of(r, period='1 yr'):
    return next((s for s in r['specs'] if s['period'] == period), None)


KEYS = ('rel', 'fs_rel', 'fs_value', 'abs')


def same_spec(a, b):
    return all(close(a[k], b[k]) for k in KEYS)


def fmt_spec(s):
    parts = []
    if s['rel']:
        parts.append(f"{s['rel'] * 1e6:.6g} ppm of reading")
    if s['fs_rel']:
        parts.append(f"{s['fs_rel'] * 1e6:.6g} ppm of range")
    if s['fs_value']:
        parts.append(f"{s['fs_value']:.6g} {s['unit']} range term")
    if s['abs'] or not parts:
        parts.append(f"{s['abs']:.6g} {s['unit']}".strip())
    return ' + '.join(parts)


def match(old, new):
    """Per old row: dict(status, old row, new candidates).  Returns (results, set of matched new indexes)."""
    O, N = flat(old), flat(new)
    out, used = [], set()
    for fo, ro in O:
        cands = []
        for i, (fn, rn) in enumerate(N):
            if rn['kind'] != ro['kind'] or fn['direction'] != fo['direction'] or rn['variant'].lower() != ro['variant'].lower():
                continue
            if not (close(rn['amp_lo'], ro['amp_lo']) and close(rn['amp_hi'], ro['amp_hi'])):
                continue
            if ro['freq_lo'] is None:
                if rn['freq_lo'] is not None:
                    continue
            elif rn['freq_lo'] is None or rn['freq_lo'] < ro['freq_lo'] - 1e-9 or rn['freq_hi'] > ro['freq_hi'] + 1e-9:
                continue
            cands.append(i)
        if not cands:
            out.append(dict(status='removed', fo=fo, ro=ro, cands=[]))
            continue
        used.update(cands)
        so = spec_of(ro)
        bad = [i for i in cands if not same_spec(so, spec_of(N[i][1]))]
        out.append(dict(status='changed' if bad else 'confirmed', fo=fo, ro=ro, cands=cands, bad=bad))
    return out, used, O, N


# ------------------------------------------------------------------------------------------------------------------------ effects
def temp_db(data, tag):
    d = tempfile.mkdtemp(prefix=f'chk5560_{tag}_')
    sdir = os.path.join(d, 'standards')
    os.makedirs(sdir)
    with open(os.path.join(sdir, 'fluke_5560a_standard.json'), 'w', encoding='utf-8') as fh:
        json.dump(data, fh)
    db = os.path.join(d, 'reg.sqlite3')
    sm.seed(directory=sdir, path=db)
    return d, db, sm.standard(MODEL, db)


# label, kind, nominal, unit, frequency, range_value, UUT tolerance (half-width, base unit)
POINTS = [
    ('10 V DC', 'DCV', 10.0, 'V', None, None, 1e-3),
    ('1 V AC 1 kHz', 'ACV', 1.0, 'V', 1000.0, None, 1e-3),
    ('100 mV AC 50 kHz', 'ACV', 0.1, 'V', 50000.0, None, 1e-3),
    ('12 A AC 40 Hz', 'ACI', 12.0, 'A', 40.0, None, 0.12),
    ('1 kohm', 'OHM', 1000.0, 'ohm', None, None, 1.0),
    ('10 uF', 'CAP', 1e-5, 'F', None, None, 1e-7),
    ('Type K 100 degC', 'TEMP', 100.0, 'C', None, None, 1.0),
    # points in the rows that changed
    ('5 nF (12 nF range)', 'CAP', 5e-9, 'F', None, None, 5e-11),
    ('100 nF (120 nF range)', 'CAP', 1e-7, 'F', None, None, 1e-9),
    ('1 nF (1.2 nF range)', 'CAP', 1e-9, 'F', None, None, 1e-11),
    ('90 uF (120 uF range)', 'CAP', 9e-5, 'F', None, None, 9e-7),
    ('1 V AC 10 Hz', 'ACV', 1.0, 'V', 10.0, None, 1e-3),
]


def quick(std, kind, nominal, unit, freq, rng, period=None):
    """(limit, row label, divisor, EMU, CMC, reported) or None.  Never raises."""
    try:
        if period:
            std.period = period
        b = ub.build(kind, nominal, unit, standard=std, frequency=freq, range_value=rng)
        h = b.hit
        return dict(limit=h.limit if h else None, row=(h.row['function'] + ' / ' + h.row['label'] + f" [{h.period}]") if h else '(no row)',
                    emu=b.emu, cmc=b.cmc, reported=b.reported, hit=h)
    except Exception as e:                      # report it, never hide it
        return dict(limit=None, row=f'error {type(e).__name__}: {e}', emu=None, cmc=None, reported=None, hit=None)


def tar_of(std, kind, nominal, unit, freq, tol):
    p = dict(kind=kind, unit=unit, nominal=nominal, range=None, frequency=freq)
    r = tartur.compute(p, -tol, tol, standard=std)
    return r


def g(x):
    return '' if x is None else f'{x:.6g}'


def tf(x):
    return tartur.format_ratio(x) or ''


def effects(old_std, new_std):
    rows = []
    for (label, kind, nom, unit, freq, rng, tol) in POINTS:
        a = quick(old_std, kind, nom, unit, freq, rng)
        b = quick(new_std, kind, nom, unit, freq, rng)
        ta = tar_of(old_std, kind, nom, unit, freq, tol)
        tb = tar_of(new_std, kind, nom, unit, freq, tol)
        rows.append(dict(label=label, tol=tol, unit=unit, a=a, b=b, ta=ta, tb=tb))
    return rows


def ninety_day(old_std, new_std):
    """The 90 day rows must change nothing for a 1 yr report: same hit, same budget, same TAR with and without the extra column."""
    res = []
    for (label, kind, nom, unit, freq, rng, tol) in POINTS:
        d = quick(new_std, kind, nom, unit, freq, rng)                         # default period (1 yr)
        e = quick(new_std, kind, nom, unit, freq, rng, period='1 yr')
        new_std.period = '1 yr'
        f = quick(new_std, kind, nom, unit, freq, rng, period='90 day')
        new_std.period = '1 yr'
        res.append((label, d, e, f))
    return res


def pv_points():
    """Capacitance / ACV / ACI / OHM points of every shipped *_pv.json whose 5560A budget differs between the old and the new sheet."""
    out = {}
    for path in sorted(glob.glob(os.path.join(HERE, 'specs', '*_pv.json'))):
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        seen = []

        def walk(o):
            if isinstance(o, dict):
                if o.get('kind') in ('CAP', 'ACV', 'ACI', 'OHM', 'OHM2', 'OHM4') and isinstance(o.get('nominal'), (int, float)):
                    seen.append(o)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(data)
        out[os.path.basename(path)] = seen
    return out


def differing_catalog_points(old_std, new_std):
    res = {}
    for name, pts in pv_points().items():
        uniq = {}
        for p in pts:
            unit = {'CAP': 'F', 'ACV': 'V', 'ACI': 'A'}.get(p['kind'], 'ohm')
            key = (p['kind'], p['nominal'], p.get('frequency'))
            if key in uniq:
                continue
            a = quick(old_std, p['kind'], p['nominal'], unit, p.get('frequency'), p.get('range'))
            b = quick(new_std, p['kind'], p['nominal'], unit, p.get('frequency'), p.get('range'))
            if not (close(a['limit'], b['limit']) and close(a['reported'], b['reported'])):
                uniq[key] = (a, b, unit)
        if uniq:
            res[name] = uniq
    return res


# ------------------------------------------------------------------------------------------------------------------------ deployment
def deployment_test(old, new):
    """Everything on temporary databases.  Returns a list of (step, result text)."""
    log = []
    d = tempfile.mkdtemp(prefix='chk5560_dep_')
    sdir_old, sdir_new = os.path.join(d, 'old'), os.path.join(d, 'new')
    for s, data in ((sdir_old, old), (sdir_new, new)):
        os.makedirs(s)
        with open(os.path.join(s, 'fluke_5560a_standard.json'), 'w', encoding='utf-8') as fh:
            json.dump(data, fh)
    db = os.path.join(d, 'owner.sqlite3')
    n = sm.seed(directory=sdir_old, path=db)
    sid = sm.standard(MODEL, db).id
    log.append(('Owner database holds the OLD sheet', f'seed loaded {n} standard(s); {len(sm.rows_of(sid, path=db))} rows.'))
    sm.set_assets(sid, [('A-1234', 'SER001')], path=db)
    sm.set_standard_field(sid, 'divisor', 2.0, who='owner', reason='test', path=db)
    rows = sm.rows_of(sid, path=db)
    cap = next(r for r in rows if r['kind'] == 'CAP')
    sm.update_row(cap['id'], {'resolution': 1e-12}, who='owner', reason='test edit', path=db)
    log.append(('Owner edits', 'one asset link (A-1234), divisor set to 2.0 explicitly, one row edited (capacitance resolution).'))
    before = len(sm.log_for(sid, path=db))
    n = sm.seed(directory=sdir_new, path=db)
    s2 = sm.standard(MODEL, db)
    log.append(('1. git pull of the NEW JSON, program started (sm.seed over the same database)',
                f'seed loaded {n} standard(s); rows still {len(s2.rows)}; assets {sm.assets_of(s2.id, path=db)}; edited rows '
                f'{sum(1 for r in sm.rows_of(s2.id, path=db) if r.get("edited"))}; log entries {before} -> {len(sm.log_for(s2.id, path=db))}. '
                'Nothing changes: seed skips a model that is already in the database.'))
    # the manual Standards Specs > Import JSON (specmanager.import_data(replace=True))
    sm.import_data(new, who='owner', path=db)
    s3 = sm.standard(MODEL, db)
    info = next(x for x in sm.standards(db) if x['model'] == MODEL)
    log.append(('2. Standards Specs > Import JSON with the NEW file (import_data, replace=True, no confirmation dialog)',
                f'standard id {sid} -> {s3.id}; rows {len(s3.rows)}; assets {sm.assets_of(s3.id, path=db)} (the cascade deleted the link); '
                f'edited rows {sum(1 for r in sm.rows_of(s3.id, path=db) if r.get("edited"))}; divisor field {info["divisor"]} (kept from the old row); '
                f'period {info["period"]} (kept); approved_by {info["approved_by"]!r}; change-log entries for the new id: {len(sm.log_for(s3.id, path=db))} '
                f'(entries of the old id {sid} stay in spec_changes, orphaned).'))
    shutil.rmtree(d, ignore_errors=True)
    return log


# ------------------------------------------------------------------------------------------------------------------------ report
def fr(x):
    return f'{x:g}' if isinstance(x, (int, float)) else str(x)


def build_report(old_rev):
    old, new = load_old(old_rev), load_new()
    results, used, O, N = match(old, new)
    conf = [r for r in results if r['status'] == 'confirmed']
    chg = [r for r in results if r['status'] == 'changed']
    rem = [r for r in results if r['status'] == 'removed']
    added = [(i, N[i]) for i in range(len(N)) if i not in used]
    dold, _, old_std = temp_db(old, 'old')
    dnew, _, new_std = temp_db(new, 'new')
    eff = effects(old_std, new_std)
    nd = ninety_day(old_std, new_std)
    cat = differing_catalog_points(old_std, new_std)
    dep = deployment_test(old, new)
    old_std_period = old_std.period

    L = []
    w = L.append
    w('# Fluke 5560A standards sheet: check against the manufacturer\'s document')
    w('')
    w(f'Document: {DOC} (31 PDF pages; printed page n = PDF page n + 2). All page numbers below are PDF pages as stored in the sheet\'s `page` field.')
    w(f'Old sheet: git revision `{old_rev}` (SpecTrack export, author / approval "{old["standard"].get("approved_by", "")}, {old["standard"].get("approve_date", "")}", '
      f'reference "{old["standard"].get("reference", "")}"). New sheet: `specs/standards/fluke_5560a_standard.json`, written by '
      '`specs/build_5560a_standard_from_manual.py` (idempotent; every row carries its page). Generated by `specs/analyze_5560a_spec_check.py`.')
    w('')
    w('Rules kept: the stored level is the 95 % column with divisor 2; period labels are `1 yr` (default) and `90 day`, as on the 3458A sheet; the 2 year '
      'columns and the 99 % columns are NOT loaded. No instrument command, limit or pass/fail logic is touched by this change.')
    w('')
    w('## 1. Counts')
    w('')
    w(f'| | rows |\n|---|---|\n| Old sheet | {len(O)} |\n| New sheet | {len(N)} |\n| Old rows confirmed (1 yr figures identical) | {len(conf)} |\n'
      f'| Old rows changed | {len(chg)} |\n| Old rows removed (not in the document) | {len(rem)} |\n| Rows added (in the document, not in the old sheet) | {len(added)} |')
    w('')
    w('Confirmed means: the 1 yr relative term, range term and floor are equal to the document\'s 95 % column (read from the rendered page images, each number read '
      'twice). Every row of the new sheet also carries the 90 day figure; those are not counted as rows (see section 6).')
    w('')
    w('## 2. The five most important differences')
    w('')
    caps = [r for r in chg if r['ro']['kind'] == 'CAP']
    w('1. **Capacitance floors were 1000 times too small on four ranges.** ' + '; '.join(
        f"{r['ro']['label']}: old {fmt_spec(spec_of(r['ro']))}, document {fmt_spec(spec_of(flat(new)[r['bad'][0]][1]))} (p.{flat(new)[r['bad'][0]][1].get('page')})" for r in caps)
      + '. The old figures look like a unit slip (fF / pF / nF). Reports and TAR at capacitance points in those ranges change (section 5).')
    two = [r for r in chg if r['fo']['name'].lower().startswith('resistance [2')]
    w('2. **2-wire resistance floors** at 12 ohm and 1200 Mohm: ' + '; '.join(
        f"{r['ro']['label']}: old {fmt_spec(spec_of(r['ro']))}, new {fmt_spec(spec_of(flat(new)[r['bad'][0]][1]))}" for r in two)
      + '. The document prints no 2-wire table; the new floors are COMPUTED from the printed formula (24 h floor + 5 uV / lowest specified stimulus current, pp.11-12). Unverified against a printed 2-wire figure.')
    acv = [r for r in chg if r['ro']['kind'] == 'ACV']
    w('3. **AC voltage 1.2 V, 5 Hz to 10 Hz**: ' + '; '.join(
        f"old {fmt_spec(spec_of(r['ro']))}, document {fmt_spec(spec_of(flat(new)[r['bad'][0]][1]))} (p.{flat(new)[r['bad'][0]][1].get('page')})" for r in acv)
      + ' (the same 75 vs 70 uV difference already noted for the 34410A suitability check in NOTES.md).')
    w('4. **Duty cycle**: the old sheet held three `input` rows (duty cycle MEASURED, 0.05 % of reading, old p.12). The document is for a source and prints no input duty figure, so those three rows are removed. '
      'The document prints the OUTPUT duty uncertainty (0.02 % of period + 100 ns at 50 %, 0.05 % of period + 100 ns for 10 % to 90 %; p.24), stored as three new output rows at 1 kHz (0.03 % / 0.06 %DC; '
      'at other frequencies the 100 ns term differs, see the problems list). The duty points of the 87V catalogue do not read these rows: `uncertainty_budget` has no DUTY lookup and `tartur` gives DUTY no ratio.')
    w(f'5. **{len(added)} rows added**: thermocouple types B, C, D, E, G, L, N, R, S, T, U, BP, XK (J and K existed), the ten RTD types, band splits '
      '(for example ACV / ACI frequency bands printed separately), and every row now has a 90 day figure. The old note 1 ("NOT checked against a 5560A specification document") '
      'no longer applies; the old approval ("Tyler, Mike A, 2/10/2026") is NOT carried over because it approved a different sheet.')
    w('')
    w('## 3. Differences row by row (old value, document value, page)')
    w('')
    w('| Function | Old row | Old (1 yr) | Document row | Document (1 yr) | Doc page |\n|---|---|---|---|---|---|')
    for r in chg:
        for i in r['bad']:
            fn, rn = N[i]
            w(f"| {r['fo']['name']} | {r['ro']['label']} (old p.{r['ro'].get('page')}) | {fmt_spec(spec_of(r['ro']))} | {rn['label']} | {fmt_spec(spec_of(rn))} | {rn.get('page')} |")
    for r in rem:
        w(f"| {r['fo']['name']} ({r['fo']['direction']}) | {r['ro']['label']} {r['ro']['amp_lo']:g}-{r['ro']['amp_hi']:g} % (old p.{r['ro'].get('page')}) | {fmt_spec(spec_of(r['ro']))} | removed | not in the document | |")
    w('')
    w('Old-sheet notes: old note 1 (the 2026-10-22 corrections of the Current, DC 12 mA range 0.0012 A -> 0.012 A and the Current, AC 30.2 A band 3.1 - 12 A -> 12 - 30.2 A) was '
      '"NOT checked against a 5560A specification document". Both corrections are CONFIRMED by the document (DCI 12 mA range p.7; ACI bands p.8), with the ppm and floor numbers unchanged. '
      'The old note is replaced by 24 notes taken from the document (confidence level, conditions, range limits, External Sense, floors in footnotes, COMP adders, standards per thermocouple type, ...).')
    w('')
    w('## 4. Rows added, by function')
    w('')
    by = {}
    for i, (fn, rn) in added:
        k = (fn['name'], fn['direction'])
        by.setdefault(k, []).append(rn)
    w('| Function | Direction | Rows added | Pages |\n|---|---|---|---|')
    for (name, direction), rs in by.items():
        pages = sorted({r.get('page') for r in rs if r.get('page') is not None})
        w(f'| {name} | {direction} | {len(rs)} | {", ".join(str(p) for p in pages)} |')
    w('')
    w('## 5. Effect on uncertainty budget and TAR (old sheet vs new sheet, 1 yr)')
    w('')
    w('Method: `uncertainty_budget.build` on two temporary databases (limit / divisor 2, EMU = 2 x RSS, reported = ceil_sig(max(EMU, scope CMC)); '
      'no resolution term because the resolution tables are not loaded) and `tartur.compute` with an illustrative UUT tolerance (shown). TAR = T / limit, no divisor.')
    w('')
    w('| Point | Old row | Old limit | New row | New limit | Old EMU | New EMU | Old reported | New reported | Tol | Old TAR | New TAR |\n|---|---|---|---|---|---|---|---|---|---|---|---|')
    for e in eff:
        a, b = e['a'], e['b']
        w(f"| {e['label']} | {a['row']} | {g(a['limit'])} | {b['row']} | {g(b['limit'])} | {g(a['emu'])} | {g(b['emu'])} | {g(a['reported'])} | {g(b['reported'])} | "
          f"{g(e['tol'])} {e['unit']} | {tf(e['ta']['tar'])} | {tf(e['tb']['tar'])} |")
    w('')
    same = [e['label'] for e in eff if close(e['a']['limit'], e['b']['limit']) and close(e['a']['reported'], e['b']['reported'])]
    w('Points with identical limit and reported uncertainty on both sheets: ' + (', '.join(same) or 'none') + '.')
    w('')
    w('### Catalogue points whose budget changes')
    w('')
    if not cat:
        w('No capacitance / ACV / ACI / OHM point of the shipped `specs/*_pv.json` catalogues has a different 5560A limit or reported uncertainty.')
    else:
        w('Points of the shipped procedure catalogues (`specs/*_pv.json`) whose 5560A limit or reported uncertainty differs (first occurrence per catalogue, kind, nominal, frequency). '
          'These are the reports that print a different Uncertainty / TAR when the sheet is replaced in a lab database.')
        w('')
        w('| Catalogue | Kind | Nominal | Freq | Old limit | New limit | Old reported | New reported |\n|---|---|---|---|---|---|---|---|')
        for name, pts in cat.items():
            for (kind, nom, freq), (a, b, unit) in pts.items():
                w(f'| {name} | {kind} | {nom:g} {unit} | {g(freq)} | {g(a["limit"])} | {g(b["limit"])} | {g(a["reported"])} | {g(b["reported"])} |')
    if cat:
        diff_rep = sum(1 for pts in cat.values() for (a, b, u) in pts.values() if not close(a['reported'], b['reported']))
        w('')
        w(f'Of these points, {diff_rep} print a different Uncertainty. Where the reported value is the same, the scope CMC (rounded up) dominates the budget on both sheets, so the printed Uncertainty and TUR '
          'do not change; only the TAR changes (TAR = tolerance / limit uses the sheet\'s limit directly).')
    w('')
    w('## 6. The 90 day rows change nothing for existing 1 yr reports')
    w('')
    w('`StandardSpec.lookup` uses `period or self.period`, and `self.period` is the standard\'s stored default, `1 yr`. A 90 day figure is used only when a caller passes '
      '`period="90 day"` explicitly or the owner changes the standard\'s default period; no procedure or report does either. The 1 yr spec is listed first in every row '
      '(three tests and the editor read `specs[0]`). Check, new sheet, default period against explicit `1 yr` (must be identical) and `90 day` (shown for information only):')
    w('')
    w('| Point | Default limit | Explicit 1 yr limit | Identical | 90 day limit (not printed anywhere) |\n|---|---|---|---|---|')
    for label, d, e, f in nd:
        w(f"| {label} | {g(d['limit'])} | {g(e['limit'])} | {'yes' if close(d['limit'], e['limit']) and close(d['reported'], e['reported']) else 'NO'} | {g(f['limit'])} |")
    w('')
    w('Old sheet default period: ' + old_std_period + '. The 1 yr figures of the 137 confirmed rows are the old figures, so for those rows a 1 yr report prints exactly what it printed before.')
    w('')
    w('## 7. How the JSON reaches lab_registry.sqlite3, and what happens on the owner\'s machine')
    w('')
    w('Tested on temporary databases (this script, `deployment_test`):')
    w('')
    for step, res in dep:
        w(f'- **{step}**: {res}')
    w('')
    w('Reading of the code:')
    w('')
    w('- `specmanager.seed()` (called when Standards Specs opens, and by `uncertainty_budget.build`, `tartur.standard_accuracy` and the engines) loads a `specs/standards/*_standard.json` only when its model is NOT in the database. A machine that already holds a 5560A keeps its rows, edits, assets and log. `sync_confidence` fills a missing confidence level only.')
    w('- Therefore **committing this JSON changes nothing on an existing owner database**; only a machine without a 5560A (new install, new database) gets the new sheet.')
    w('- The only code path that replaces it is the manual Standards Specs > Import JSON (`import_data(replace=True)`): it deletes the standard row, which cascades to the spec rows and the asset links (`standard_assets`), and inserts the new sheet. It keeps only the divisor and the default period; hand edits (`edited` rows, resolutions) and the asset links are lost, approved_by / approve_date come from the file (blank here), and there is NO confirmation dialog. The change log keeps an `import` entry for the new id, and the old id\'s entries stay in `spec_changes`.')
    w('- The spec editor\'s `rebuild_sheet` is an in-place resync that keeps edits, but it runs only for a documented edit of a spec file made in the editor; it is not a deployment path for this change.')
    w('- No existing machinery was run against the owner\'s database, and none will silently overwrite owner edits as long as nobody uses Import. The decision how to update a database that already holds the old 5560A sheet is left to the owner (question 8).')
    w('')
    w('## 8. What the document does not give, or the schema cannot hold')
    w('')
    for p in new.get('problems', []):
        w(f"- [{p['level']}] {p['where']}: {p['what']}")
    w('')
    w('## 9. Appendix: all old rows')
    w('')
    w('| # | Function | Old row | Old page | Status | New page(s) |\n|---|---|---|---|---|---|')
    for k, r in enumerate(results, 1):
        pages = sorted({N[i][1].get('page') for i in r['cands'] if N[i][1].get('page') is not None})
        w(f"| {k} | {r['fo']['name']} ({r['fo']['direction']}) | {r['ro']['label']} | {r['ro'].get('page')} | {r['status']} | {', '.join(str(p) for p in pages)} |")
    w('')
    for d in (dold, dnew):
        shutil.rmtree(d, ignore_errors=True)
    summary = dict(old=len(O), new=len(N), confirmed=len(conf), changed=len(chg), removed=len(rem), added=len(added))
    return '\n'.join(L) + '\n', summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old-rev', default='794aeff')
    ap.add_argument('--out', default=DEFAULT_OUT)
    a = ap.parse_args()
    text, summary = build_report(a.old_rev)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    print(summary, '->', a.out)


if __name__ == '__main__':
    main()
