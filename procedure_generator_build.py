"""Procedure Generator: accepted rows -> a Datasheet Builder sheet -> a registered, runnable procedure (no Qt, no network).

    datasheet_from_project(p)            the Datasheet (Decimal, exact printed limits) for the rows the reviewer accepted
    build(p, store, who, ...)            gate check, sheet, standard for the uncertainty, save (datasheet_builder.save), register as a GENERATED DRAFT (generated_draft)

It REUSES the Datasheet Builder: the sheet is the same model the Mudcats import (mdd_convert) produces and the runtime is dsb_runtime.DsbApp, so reset before the first point, standby
after each point, padding of typed readings, judging, checkpoints, TAR / TUR, procedure modifications and the 'Calibration Data' PDF are the engine's own.
    MANUAL    options.manual_entry: nothing is sourced or read by the program; every reading is typed.
    ONE-WAY   the standards matcher picks the calibrator / standard for each point (5522A, 5560A ...); the unit under test is read by the technician (typed).
TWO-WAY is not built in this release (build() returns a result that says so, and changes nothing).

Nothing is invented: a quantity is whatever the reviewer accepted; a range, frequency or level that is not given stays empty; limits are the printed limits (exact), or are
calculated from a printed accuracy statement and listed as such.  Everything doubtful goes into the UNVERIFIED list that is stored with the procedure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

import datasheet_builder as db
import generated_draft
import procedure_generator as pg

D = Decimal
GENERATED_BY = 'Procedure Generator'
_PREFIX_BY_EXP = {-12: 'p', -9: 'n', -6: 'µ', -3: 'm', 0: '', 3: 'k', 6: 'M', 9: 'G'}
_NUM = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)')


@dataclass
class BuildResult:
    ok: bool = False
    message: str = ''
    uid: str = ''
    version: int = 0
    status: str = ''
    kind: str = ''
    points: int = 0
    mode: str = ''
    unverified: list = field(default_factory=list)
    uncertainty_missing: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    standard: str = ''
    coming: bool = False


def _decimals(text: str) -> int:
    m = _NUM.match(pg.norm_qty(text))
    return len(m.group(0).partition('.')[2]) if m else 0


def _prefix_of(text: str, si: Decimal) -> str:
    """The SI prefix the person's text used ('mV' -> 'm'), worked out from the number and its SI value so the display follows what the table printed."""
    m = _NUM.match(pg.norm_qty(text))
    if not m:
        return ''
    num = D(m.group(0))
    if num == 0 or si == 0:
        return ''
    try:
        return _PREFIX_BY_EXP.get((si / num).adjusted(), '')
    except Exception:
        return ''


def _label(r: pg.Row) -> str:
    bits = [r.nominal.strip()]
    if r.frequency.strip():
        bits.append(r.frequency.strip())
    return ' '.join(b for b in bits if b)


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', (text or '').lower()).strip('_')[:30] or 'sec'


def datasheet_from_project(p: pg.Project):
    """(Datasheet, notes).  Only rows with status accepted / edited; the caller has already passed pg.gate().  Raises db.DsError if a row cannot be converted
    (validation should have caught it: that is a bug, not a user mistake)."""
    notes = []
    manual = p.mode == pg.MANUAL
    models = [p.model.strip()]
    ds = db.Datasheet((p.make or '').strip() or 'Unknown make', models[0] or 'Unknown model', p.name.strip())
    ds.revision = 'generated ' + pg._now()[:10]
    ds.set_periods([db.Period('1y', '1 year')], '1y')
    period = '1y'
    srcs = [f for f in p.files_of(pg.ROLE_SPEC) if f.id in {r.file_id for r in pg.in_procedure(p)}] or p.files_of(pg.ROLE_SPEC)
    pages = '; '.join(f'{f.original} pp. {p.pages[f.id][0]}-{p.pages[f.id][1]}' for f in srcs if f.id in p.pages)
    ds.source = dict(document=f'{", ".join(f.original for f in srcs)} (read by the Procedure Generator, project {p.id})', pages=pages,
                     note='Generated from the manual by the Procedure Generator and reviewed by a person against the page images. ' +
                          'Source files (sha256): ' + '; '.join(f'{f.original} {f.sha256[:16]}' for f in srcs) + '. DRAFT until approved by the owner.')
    ds.options.update(manual_entry=manual, function_prompt=not manual, generated=p.id)
    order = {f.id: i for i, f in enumerate(p.files)}
    rows = sorted(pg.in_procedure(p), key=lambda r: (order.get(r.file_id, 999), r.page))      # stable: the reader's order within a page
    groups: dict = {}
    for r in rows:
        groups.setdefault((r.function, r.section.strip() or db.KINDS[r.function]['name']), []).append(r)
    n = 0
    used_ids = set()
    for (kind, section), items in groups.items():
        info = db.KINDS[kind]
        unit = info['unit']
        fid = f'{_slug(section)}_{kind.lower()}'
        base, k = fid, 1
        while fid in used_ids:
            k += 1
            fid = f'{base}_{k}'
        used_ids.add(fid)
        fn = ds.add_function(kind, section, id=fid, settings={'source': 'generated'})
        ranges: dict = {}                                     # key -> Range

        def range_for(r, nominal_si, lows_highs):
            rv = None
            if r.range.strip() and unit:
                rv, why = pg.qty(r.range, unit)
                if why:
                    rv = None
            pre = _prefix_of(r.nominal, nominal_si) if (r.nominal.strip() and nominal_si is not None) else ''
            key = ('v', rv) if rv is not None else ('u', pre)
            if key in ranges:
                return ranges[key]
            if rv is not None:
                fs, settings = abs(rv), {}
            else:
                vals = [abs(v) for v in ([nominal_si] + lows_highs) if v is not None]
                fs = max(vals) if vals else D(1)
                if fs <= 0:
                    fs = D(1)
                settings = {'unspecified': True, 'display_prefix': pre}
            used = {x.full_scale for x in fn.ranges}
            while fs in used:
                fs = fs * (D(1) + D(10) ** -9)
            rng = fn.add_range(fs, id=f'r{len(fn.ranges) + 1}', label=r.range.strip() if rv is not None else '',
                               display_unit=pre if unit not in db._NO_PREFIX else '', settings=settings)
            ranges[key] = rng
            return rng
        for r in items:
            n += 1
            nominal = None
            if r.nominal.strip() and not info.get('passfail') and kind != 'CHECK':
                nominal, _w = pg.qty(r.nominal, unit)
            lo = hi = None
            if r.low.strip() and r.high.strip():
                lo, _w = pg.qty(r.low, unit)
                hi, _w2 = pg.qty(r.high, unit)
            freq = pg.qty(r.frequency, 'Hz')[0] if r.frequency.strip() else None
            level = pg.qty(r.level, 'V')[0] if (r.level.strip() and info.get('amplitude') and kind in ('FREQ', 'PERIOD', 'GEN_FREQ', 'SCOPE_BW', 'SCOPE_TRIGGER', 'GEN_FLAT')) else None
            if nominal is None:
                nominal = D(0) if (kind == 'CHECK' or info.get('passfail')) else ((lo + hi) / 2 if lo is not None else D(0))
            rng = range_for(r, nominal, [x for x in (lo, hi) if x is not None])
            pt = db.Point(f'{fn.id}.p{n:04d}', rng.id, nominal, freq, level, label=_label(r), origin=f'generated:{r.id}',
                          note='. '.join(x for x in (f'Manual p. {r.page}' + (f' step {r.step}' if r.step else ''), r.section.strip(),
                                                      ('Accuracy as printed: ' + r.accuracy.strip()) if r.accuracy.strip() and lo is None else '',
                                                      ('Level: ' + r.level.strip()) if r.level.strip() and level is None else '',
                                                      ('Reader note: ' + r.note) if r.note else '') if x))
            fn.points.append(pt)
            dec = max([_decimals(x) for x in (r.low, r.high, r.nominal) if x.strip()] + [0])
            if dec:
                pt.settings['decimals'] = dec
            if kind == 'TEMP' and r.tc_type.strip():
                pt.settings['sensor'] = r.tc_type.strip().upper()
            if lo is not None:
                pt.overrides[period] = {'low': db.fmt(lo), 'high': db.fmt(hi)}
            elif r.accuracy.strip():
                pt.spec = db.SpecEntry({period: db.parse_expr(r.accuracy, unit or '')}, printed={period: r.accuracy.strip()}, note='printed accuracy statement (no limits printed)')
                notes.append(f'p. {r.page} step {r.step or "-"}: limits calculated from the printed accuracy "{r.accuracy.strip()}"')
    return ds, notes


def _gaps(ds):
    """(sheet check without the dry run, [point ids] that should carry an uncertainty and have none and no waiver)."""
    import datasheet_builder_rules as dsr
    chk = dsr.check(ds, dry_run_on=False)
    return chk, [pid for pid, s in chk.sources.items() if s.level == dsr.ERROR]


def build(p: pg.Project, store: pg.Store, who: str, registry=None, root=None, matcher=None, standard=None, replace_uid=None) -> BuildResult:
    """Build and register the procedure.  Returns a BuildResult; a refusal changes nothing.  `standard` = the uncertainty standard of a MANUAL sheet ('' = none: waive,
    None = the best fit); `registry` / `root` are datasheet_builder.save's (tests give their own)."""
    res = BuildResult(mode=p.mode)
    g = pg.gate(p)
    if g.stage == 'coming':
        res.coming, res.message = True, pg.TWOWAY_COMING
        return res
    if not g.can_click:
        res.message = g.text
        return res
    import datasheet_builder_rules as dsr
    try:
        ds, notes = datasheet_from_project(p)
        photos = p.files_of(pg.ROLE_PHOTO)
        if photos and p.mode != pg.MANUAL:                      # the owner's photo of the hook-up: stored with the project, offered as the reference image of the setup prompt
            ds.options['hookup_photo'] = str(store.file_path(p, photos[-1].id))
    except (db.DsError, KeyError, ValueError) as exc:
        res.message = f'The accepted rows could not be turned into a sheet: {exc}'
        return res
    ds.uid = replace_uid or (p.build.get('uid') or '')
    unverified = pg.unverified_list(p) + notes
    unverified.append('The calibration interval of the printed limits is not read from the manual: "1 year" is a placeholder period. Confirm it against the manual.')
    if p.mode == pg.MANUAL:
        import mdd_convert as mc
        if standard is None:
            standard = mc.best_standard(mc.standard_fits(ds, matcher=matcher))
        dsr.apply_manual_standard(ds, standard or '', who=f'{GENERATED_BY} ({who})', matcher=matcher)
        res.standard = standard or ''
        unverified.append(f'Uncertainty standard for the typed readings: {standard or "none (every uncertainty waived)"}. Confirm it is the standard the technician will use.')
        chk, gaps = _gaps(ds)
    else:
        chk, gaps = _gaps(ds)
    if gaps:                                                    # a reading that should carry an uncertainty and has none: a RECORDED waiver, never a silent blank
        by_point = {pid: (fn, pt) for fn, pt in ds.all_points() for pid in [pt.id]}
        codes: dict = {}
        for pid in gaps:
            fn, pt = by_point[pid]
            code = 'not_implemented' if fn.kind not in (dsr.MANUAL_RESOLVABLE_KINDS if ds.options.get('manual_entry') else dsr.RESOLVABLE_KINDS) else 'no_source'
            codes.setdefault(code, []).append(pid)
            res.uncertainty_missing.append(f'{dsr.point_text(fn, pt)}: {chk.sources[pid].text}')
        for code, pids in codes.items():
            dsr.set_waiver(ds, pids, code, 'Procedure Generator: no standard in the suite gives an uncertainty for this point; the owner must decide before approval', who=GENERATED_BY)
        unverified.append(f'{len(gaps)} point(s) should carry an uncertainty and have none (waived and recorded): see the build summary.')
    chk2 = dsr.check(ds, dry_run_on=False)
    for f in chk2.findings:
        if f.level == dsr.WARN:
            unverified.append(f'Sheet check, rule {f.rule}: {f.text}')
    for u in chk2.unverified:
        unverified.append('Unverified command: ' + u.line())
    res.unverified = list(dict.fromkeys(unverified))
    saved = db.save(ds, who=f'{GENERATED_BY} ({who})', note=f'Generated from project {p.id} ({p.name}); DRAFT until approved by the owner', root=root, db=registry)
    res.uid, res.version, res.status, res.kind, res.problems = saved.uid, saved.version, saved.status, saved.kind, [str(x) for x in saved.problems]
    res.points = sum(len(f.points) for f in ds.functions)
    if not saved.ok or saved.status != 'ready':
        res.message = ('The procedure was not registered: the Datasheet Builder sheet check found problems: ' + '; '.join(res.problems[:3]) if saved.ok else
                       'Not saved: ' + '; '.join(res.problems[:3]))
        p.build = {**p.build, 'last_status': saved.status, 'uid': saved.uid if saved.ok else p.build.get('uid', '')}
        store.save(p)
        return res
    srcs = {f.original: f.sha256 for f in p.files if f.role in (pg.ROLE_SPEC,) and f.id in {r.file_id for r in pg.in_procedure(p)}}
    photos = {f.original: f.sha256 for f in p.files_of(pg.ROLE_PHOTO)}
    sources = dict(spec_files=srcs, photos=photos, project=p.id, folder=str(store.folder(p.id)))
    generated_draft.register(saved.uid, p.id, saved.version, p.mode, p.name, who, res.points, res.unverified, sources, db=registry)
    p.build = dict(uid=saved.uid, version=saved.version, at=pg._now(), points=res.points, standard=res.standard, title=p.name, kind=saved.kind,
                   source_files=srcs, unverified=len(res.unverified), by=who)
    store.save(p)
    res.ok = True
    res.message = (f'Registered "{p.name}" as a DRAFT procedure ({res.points} points, {"Manual" if saved.kind == "manual" else "Automated"} Calibrations tab). '
                   f'It must be approved by the owner before the draft marking is removed.')
    return res
