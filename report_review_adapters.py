"""Review-window adapters for the oscilloscope and function-generator engines (phase 2): fgen (33210A / 33220A / 33250A), MDO4000C, TDS2000C, WaveSurfer.

Tk-free, no engine is edited.  Each adapter turns what the engine is about to print (`certificate_pairs()` / WaveSurfer's `certificate_rows(kind)` and
`certificate_source_records(kind)`) into report_review_model.PointSpec rows whose `calc(standard)` re-uses the ENGINE'S OWN functions for the default
(so an untouched row prints exactly what it printed before) and, where a calibrator budget is behind the number, uncertainty_budget for another standard:

    MDO4000C   DC gain, DC offset, DVM DC          5560A budget (uncertainty_budget.osc_dc) vs the scope's oscilloscope DC CMC  -> drop-down 5560A / 5522A / 5520A
    WaveSurfer DC gain, DC offset, trigger level   same (`_dc_budget_value`)                                                   -> drop-down
    fgen       AC amplitude / LF flatness          Fluke 5790B MEASURES the point                                              -> read-only
    everything else                                scope CMC alone or the editable reference-CMC file                         -> read-only

A row the lab scope does not cover (the engine prints N/A or nothing for a point that should carry an uncertainty) is 'Not in scope' and may take a typed
uncertainty (report_review_model.Row.set_typed); a point that is not an uncertainty point at all (self-test, pass / fail, no stimulus) is 'No uncertainty'.
"""
from __future__ import annotations

import math
import sys

import report_review_model as M

SOURCE_FOR_DC = M.SOURCE_STANDARDS


def _mod(app):
    return sys.modules[type(app).__module__]


def _round_up(v):
    import uncertainty
    return uncertainty.round_up(v) if v else None


def _tur_fields(tol, unit, acc, acc_unit, value, vunit):
    import tartur
    r = tartur.ratio_fields(tartur.from_values(tol, unit, acc, acc_unit, _round_up(value) if value else None, vunit))
    return r.get('TAR', ''), r.get('TUR', '')


def _q(kind, nominal, unit):
    return dict(kind=str(kind), nominal=nominal if isinstance(nominal, (int, float)) else 0.0, unit=unit or '', frequency=None, range=None, source='adapter')


def _floats(a, b):
    return (a if isinstance(a, (int, float)) and not isinstance(a, bool) else None, b if isinstance(b, (int, float)) and not isinstance(b, bool) else None)


# ---------------------------------------------------------------------------------------------------------------------------------- generic pieces
def _fixed(spec_unit, std, printed, tar, tur, cmc=None, emu=None, value=None, expects=True, vunit=None):
    """An Evaluation for a row whose number the engine already printed (read-only rows)."""
    import uncertainty
    rep = uncertainty.round_up(value) if value else None
    return M.make_evaluation(vunit or spec_unit, std, printed, emu, cmc, rep, tar, tur, expects)


def _dc_levels_options(levels, term):
    """The calibrators whose sheet describes every DC level (uncertainty_budget.osc_dc) - the drop-down of a row with a calibrator budget."""
    import uncertainty_budget as ub
    out = []
    for key in SOURCE_FOR_DC:
        try:
            if all(ub.osc_dc(v, term, key) is not None and ub.osc_dc(v, term, key).hit is not None for v in levels):
                out.append(key)
        except Exception:
            continue
    return out


def _dc_calc(levels, term, vdiff, tol, unit, default_std, printed, default_ratio, acc_for):
    """calc(standard) of a DC point sourced by a calibrator: the larger of the calibrator budget and the scope's oscilloscope DC CMC at each level
    (uncertainty_budget.osc_dc, absolute volts); a gain point combines the levels in quadrature as a percentage of the expected difference.
    The default standard returns the engine's own strings (printed text, its TAR / TUR); another standard is recalculated."""
    import uncertainty
    import uncertainty_budget as ub

    def calc(standard):
        std = standard or default_std
        bs = [ub.osc_dc(v, term, std) for v in levels]
        if not bs or any(b is None for b in bs):
            return M.make_evaluation(unit if not vdiff else '%', std, '' if std != default_std else printed, None, None, None, '', '', True)
        if vdiff:                                               # gain: percentage of the expected difference
            part = lambda f: 100 * math.hypot(*[f(b) for b in bs]) / abs(vdiff)                     # noqa: E731
            value = part(lambda b: b.value)
            emu = part(lambda b: b.emu) if all(b.emu for b in bs) else None
            cmc = part(lambda b: b.cmc) if all(b.cmc for b in bs) else None
            vunit = '%'
        else:
            b = bs[0]
            value, emu, cmc, vunit = b.value, b.emu, b.cmc, 'V'
        text = uncertainty.format_value(value, vunit)
        if std == default_std:
            tar, tur = default_ratio
            text = printed or text
        else:
            acc = au = None
            if acc_for:
                acc, au = acc_for(std)
            tar, tur = _tur_fields(tol, unit, acc, au, value, vunit)
        return M.make_evaluation(vunit, std, text, emu, cmc, uncertainty.round_up(value) if value else None, tar, tur, True)
    return calc


# ---------------------------------------------------------------------------------------------------------------------------------- MDO4000C
def mdo_specs(app, mod):
    import tartur
    import report_pdf
    pairs = app.certificate_pairs()
    specs = []
    for i, (p, row) in enumerate(pairs):
        printed = row.get('Uncertainty', '')
        low, high = _floats(p.get('low'), p.get('high'))
        unit = p['unit']
        nominal = p.get('nominal') if p.get('nominal') is not None else 0.0
        expects = not ((p['stim'] == 'none' and p['kind'] not in mod.FREQ_CMC_KINDS) or p.get('passfail')) and p['kind'] != 'SELFTEST'
        ratios = app.tar_tur_for(p)
        default_ratio = (ratios.get('TAR', ''), ratios.get('TUR', ''))
        tol = tartur.half_width(low, high)
        spec = M.PointSpec(i, str(p.get('id', i + 1)), row.get('Section', ''), row.get('Description', ''), row.get('Nominal', ''), _q(p['kind'], nominal, unit),
                           _q(p['kind'], nominal, unit), low, high, unit, None, 'Scope CMC / reference file: read-only', dict(Uncertainty=printed), expects=expects,
                           std_label='Scope CMC')
        spec.printed.update(TAR=default_ratio[0], TUR=default_ratio[1])
        k = p['kind']
        levels = term = vdiff = None
        if k == 'OFFSET':
            levels, term = [p['offset']], p['term']
        elif k == 'DVMDC':
            levels, term = [p['nominal']], '1M'
        elif k == 'GAIN':
            levels, term, vdiff = [p['vneg'], p['vpos']], p['term'], p['vdiff']
        if levels is not None and printed not in ('', 'N/A'):
            acc_for = None
            if k in ('OFFSET', 'DVMDC') and p.get('stim') == 'cal':
                lvl = abs(p['offset'] if k == 'OFFSET' else p['nominal'])
                acc_for = lambda std, lvl=lvl: tartur.standard_accuracy(std, 'DCV', lvl)      # noqa: E731
            std = mod.CAL_MODEL
            opts = _dc_levels_options(levels, term)
            if std not in opts:
                opts.insert(0, std)
            spec.default_std, spec.locked, spec.options, spec.std_label = std, '', opts, ''
            spec.calc = _dc_calc(levels, term, vdiff, tol, unit, std, printed, default_ratio, acc_for)
        elif k == 'ABSAMP' and expects and _rf_budget(p) is not None:
            _rf_level_spec(spec, p, tol, printed, default_ratio)
        else:
            sc = report_pdf.scope()
            spec.calc = _read_only_calc(app, p, mod, row, default_ratio, expects, sc)
            if not expects:
                spec.locked = 'Not an uncertainty point'
                spec.std_label = ''
        specs.append(spec)
    return specs, M.first_default(specs)


RF_STD = '96270A'


def _rf_budget(p, standard=RF_STD, scope=None):
    """MDO4000C absolute amplitude / level flatness sweep: the Fluke 96270A level accuracy over every frequency the sweep sets (uncertainty_budget.rf_level),
    or None when the sheet does not cover the whole sweep.  The lab scope has no RF level CMC, so there is no floor (cmc None)."""
    import uncertainty_budget as ub
    return ub.rf_level_sweep(p, standard, scope=scope)


def _rf_level_spec(spec, p, tol, printed, default_ratio):
    """The 96270A is the default and only standard of an MDO4000C RF level row it covers.  The engine prints N/A for these rows; the review carries the 96270A
    value into the report (PointSpec.engine_printed -> Row.applied -> changes).  Units stay dB (no conversion): TUR = +/-tolerance / reported, TAR = tolerance /
    the sheet's printed limit, both only because tolerance, limit and uncertainty are all in dB."""
    import tartur
    import uncertainty

    def calc(standard):
        b = _rf_budget(p)
        if b is None:
            return M.make_evaluation('dB', RF_STD, '', None, None, None, '', '', True)
        rep = b.reported
        r = tartur.ratio_fields(tartur.from_values(tol, 'dB', b.hit.limit, 'dB', rep, 'dB'))
        status_cmc = b.cmc
        return M.make_evaluation('dB', RF_STD, uncertainty.format_value(rep, 'dB'), b.emu, status_cmc, rep, r.get('TAR', ''), r.get('TUR', ''), True)
    ev = calc(RF_STD)
    # a row with no scope entry that has a standard budget is 'As budgeted' (make_evaluation would call it 'Not in scope')
    def calc_ok(standard, _c=calc):
        e = _c(standard)
        if e.cmc is None and e.reported:
            e.status = M.AS_BUDGETED
        return e
    spec.calc = calc_ok
    ev = calc_ok(RF_STD)
    spec.engine_printed = dict(spec.printed)
    spec.printed = dict(Uncertainty=ev.unc_text, TAR=ev.tar, TUR=ev.tur)
    spec.default_std, spec.options, spec.locked, spec.std_label = RF_STD, [RF_STD], '', ''


def _read_only_calc(app, p, mod, row, default_ratio, expects, sc):
    """MDO4000C / TDS2000C: the engine's own number (uncertainty_parts) is the scope CMC or the reference-file value."""
    unit = p['unit']
    printed = row.get('Uncertainty', '')
    try:
        parts = mod.uncertainty_parts(p, _raw_of(app, p))
    except Exception:
        parts = None
    value = parts[0] if parts else None
    vunit = parts[1] if parts else unit
    style = parts[2] if parts else ''
    cmc = value if (parts and style in ('si', 'bw', 'bwv')) else None   # a scope CMC (not the editable reference file)
    return lambda standard: _fixed(unit, None, printed, default_ratio[0], default_ratio[1], cmc=cmc, value=value, expects=expects, vunit=vunit)


def _raw_of(app, p):
    key = str(p['id'])
    r = app.found.get(key)
    if not r or r.get('result') not in ('PASS', 'FAIL'):
        r = app.left.get(key) or {}
    return r.get('raw', {})


# ---------------------------------------------------------------------------------------------------------------------------------- TDS2000C
def tds_specs(app, mod):
    import tartur
    specs = []
    for i, (p, row) in enumerate(app.certificate_pairs()):
        printed = row.get('Uncertainty', '')
        low, high = _floats(p.get('low'), p.get('high'))
        unit = p['unit']
        nominal = p.get('nominal') if p.get('nominal') is not None else 0.0
        expects = not (p['stim'] == 'none' or p.get('passfail')) and p['kind'] != 'SELFTEST'
        ratios = app.tar_tur_for(p)
        default_ratio = (ratios.get('TAR', ''), ratios.get('TUR', ''))
        spec = M.PointSpec(i, str(p.get('id', i + 1)), row.get('Section', ''), row.get('Description', ''), row.get('Nominal', ''), _q(p['kind'], nominal, unit),
                           _q(p['kind'], nominal, unit), low, high, unit, None, 'Scope CMC: read-only' if expects else 'Not an uncertainty point',
                           dict(Uncertainty=printed, TAR=default_ratio[0], TUR=default_ratio[1]), expects=expects, std_label='Scope CMC' if expects else '')
        spec.calc = _read_only_calc(app, p, mod, row, default_ratio, expects, None)
        specs.append(spec)
    return specs, None


# ---------------------------------------------------------------------------------------------------------------------------------- function generators
def fgen_specs(app, mod):
    import report_pdf
    import tartur
    sc = report_pdf.scope()
    specs = []
    for i, (p, row) in enumerate(app.certificate_pairs()):
        printed = row.get('Uncertainty', '')
        unit = p['unit']
        low, high = _floats(p['nominal'] - p['error'], p['nominal'] + p['error'])
        expects = p['kind'] != 'SELFTEST'
        try:
            value, vunit, src = mod.uncertainty_value(p)
        except Exception:
            value, vunit, src = None, None, ''
        cmc = emu = None
        if sc is not None and p['kind'] in ('ACAMP', 'LFFLAT', 'TIMEBASE'):
            kind = 'FREQ' if p['kind'] == 'TIMEBASE' else 'ACV'
            try:
                cmc = sc.dmm(kind, p['nominal'], None, None if kind == 'FREQ' else p['frequency'], basis='measure')
            except Exception:
                cmc = None
            try:
                b = mod.measure_budget(p, sc)
                emu = b.emu if b is not None else None
            except Exception:
                emu = None
        ratios = mod.tar_tur_fields(p)
        label = {'budget': 'Fluke 5790B', 'scope': 'Scope CMC', 'reference file': 'Reference file'}.get(src, '')
        spec = M.PointSpec(i, str(p.get('id', i + 1)), row.get('Section', ''), row.get('Description', ''), row.get('Nominal', ''), _q(p['kind'], p['nominal'], unit),
                           _q(p['kind'], p['nominal'], unit), low, high, unit, None,
                           'Measured against the lab standard: read-only' if expects else 'Not an uncertainty point',
                           dict(Uncertainty=printed, TAR=ratios.get('TAR', ''), TUR=ratios.get('TUR', '')), expects=expects, std_label=label)
        spec.calc = (lambda standard, _u=unit, _p=printed, _r=ratios, _c=cmc, _e=emu, _v=value, _vu=vunit, _x=expects:
                     _fixed(_u, None, _p, _r.get('TAR', ''), _r.get('TUR', ''), cmc=_c, emu=_e, value=_v, expects=_x, vunit=_vu or _u))
        specs.append(spec)
    return specs, None


# ---------------------------------------------------------------------------------------------------------------------------------- WaveSurfer
TITLES = {'noise': 'RMS Noise', 'dcv': 'DC Gain (1 MOhm)', 'impedance': 'Input Impedance', 'offset': 'DC Offset', 'bandwidth': 'Bandwidth',
          'timebase': 'Time Base Accuracy', 'trigger': 'Trigger Level Accuracy'}
NO_INPUT_KINDS = ('noise',)          # WaveSurfer RMS noise: the scope measures its own noise with the input terminated (owner: no uncertainty)
ORDER = ('noise', 'dcv', 'impedance', 'offset', 'bandwidth', 'timebase', 'trigger')
DC_KINDS = ('dcv', 'offset', 'trigger')


def wavesurfer_specs(app, mod, kinds=None):
    import tartur
    sections = [k for k in ORDER if (kinds is None or k in kinds) and app.certificate_rows(k)]
    specs = []
    i = 0
    for kind in sections:
        rows = app.certificate_rows(kind, with_uncertainty=True)
        recs = app.certificate_source_records(kind)
        keys = app._TOL_KEYS.get(kind)
        for row, r in zip(rows, recs):
            row = dict(row)
            printed = row.get('Uncertainty', '')
            low = high = None
            unit = row.get('UOM', '')
            if keys:
                low, high = _floats(r.get(keys[0]), r.get(keys[1]))
                unit = keys[2]
            ratios = app.tar_tur_fields(kind, r)
            default_ratio = (ratios.get('TAR', ''), ratios.get('TUR', ''))
            nominal = r.get('nominal_v', r.get('nominal_ohm', r.get('nominal_hz', 0.0)))
            spec = M.PointSpec(i, f'{kind[:3]}-{row.get("Seq.", i + 1)}', TITLES[kind], row.get('Description', ''), row.get('Nominal', ''),
                               _q(kind, nominal, unit), _q(kind, nominal, unit), low, high, unit, None, 'Scope CMC: read-only',
                               dict(Uncertainty=printed, TAR=default_ratio[0], TUR=default_ratio[1]), expects=True, std_label='Scope CMC')
            if kind in NO_INPUT_KINDS:                    # self-measured: nothing is applied by a calibrator, so no uncertainty is assigned or expected
                spec.expects, spec.std_label, spec.locked = False, '', 'No input from a calibrator: no uncertainty required'
                spec.calc = (lambda standard, _u=unit, _p=printed, _r=default_ratio:
                             _fixed(_u, None, _p, _r[0], _r[1], expects=False))
            elif kind in DC_KINDS and printed:
                if kind == 'trigger':
                    level = max(abs(r['short_v']), abs(r['past_v'])) if ('short_v' in r and 'past_v' in r) else abs(r['level_v']) + mod.TRIG_LIMIT_V
                else:
                    level = r['nominal_v']
                tol = tartur.half_width(low, high)
                std = '5560A'
                opts = _dc_levels_options([level], '1M')
                if std not in opts:
                    opts.insert(0, std)
                acc_for = (lambda s, lvl=abs(level): tartur.standard_accuracy(s, 'DCV', lvl))
                spec.default_std, spec.locked, spec.options, spec.std_label = std, '', opts, ''
                spec.calc = _dc_calc([level], '1M', None, tol, unit, std, printed, default_ratio, acc_for)
            else:
                try:
                    parts = app.scope_uncertainty_value(kind, r)
                except Exception:
                    parts = None
                value, vunit = (parts if parts else (None, unit))
                spec.calc = (lambda standard, _u=unit, _p=printed, _r=default_ratio, _c=value, _v=value, _vu=vunit:
                             _fixed(_u, None, _p, _r[0], _r[1], cmc=_c, value=_v, expects=True, vunit=_vu or _u))
            specs.append(spec)
            i += 1
    return specs, M.first_default(specs)


# ---------------------------------------------------------------------------------------------------------------------------------- dispatch
def specs_for(app, kinds=None):
    mod = _mod(app)
    if hasattr(app, 'certificate_source_records') and hasattr(app, 'scope_uncertainty_value'):
        return wavesurfer_specs(app, mod, kinds)
    if hasattr(app, 'certificate_pairs'):
        if hasattr(mod, 'measure_budget'):
            return fgen_specs(app, mod)
        if hasattr(mod, 'CAL_MODEL'):
            return mdo_specs(app, mod)
        if hasattr(mod, 'uncertainty_parts'):
            return tds_specs(app, mod)
    raise TypeError('engine not covered by the review window')
