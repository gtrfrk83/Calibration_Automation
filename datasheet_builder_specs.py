"""Datasheet Builder: datasheet -> runnable spec JSON (and back), and the validator for the schema extension.

    import datasheet_builder_specs as dsp
    res = dsp.export_spec(ds, period=None, plan=None, uid=None)     # ExportResult(spec, problems, notes); spec is None when there are errors
    problems = dsp.validate_spec_ext(spec)                          # also reached through procspec.validate_manual_reading(spec)
    ds = dsp.datasheet_from_spec(spec)                              # the datasheet a spec carries (None when it has none)

The spec uses the EXISTING handheld schema ('kind': 'manual-reading', schema 2: steps[], models{}, options{}, source{}) so handheld_dmm.points_for()
and the handheld engine list and run the DMM-type points unchanged.  Everything new lives in keys the engine ignores (schema extension 'dsb'):

  top level   user_built        true
              dsb               {schema 'dsb-1', uid, version, revision, title, make, model, exported_at, period, periods[{id,label}], default_period,
                                 engine {stock_runnable, points, runnable, hand_set, notes[]}, datasheet {the full datasheet, so a spec file is also a
                                 datasheet backup and the Datasheet Builder can re-open it}, plan {optional matcher snapshot}}
  per step    dsb               {function, kind, direction ('measure' = UUT measures a stimulus; 'source' = UUT outputs, a standard measures),
                                 point_id (= step id), range_id, unit (SI base unit of nominal / limits), engine_ready (the stock handheld engine can drive it),
                                 stimulus {nominal, frequency, amplitude, settings{}}, limit {nominal, low, high, minus, plus, source 'spec'|'override',
                                 one_sided, periods{id: {low, high}}}, assignment {standard, mode 'auto'|'override'|'none', ...} (optional)}

All values inside `dsb` are SI base units as strings (exact Decimal text); the engine fields (low, high, nominal, factor, applied) follow the existing
convention: low / high are strings in the DISPLAY unit (display_unit, factor = display unit in base units), applied.value / nominal are base-unit numbers.

How each kind reaches the stock engine ('engine_ready' true = it drives the calibrator itself; false = a hand-set point, kind NONE / VISUAL, group NONE:
the operator follows the setup text and types the reading; the runtime stage replaces those with real drivers using step.dsb.stimulus):
  DCV ACV DCI ACI CAP TEMP     the same kind;  OHM2 / OHM4 -> OHM;  DIODE -> DCV (the calibrator supplies the volts);  CONT -> OHM beeper test
  FREQ / PERIOD                kind ACV at frequency (applied.value = amplitude, applied.frequency = f; base_unit Hz / s) like the 87V / 110 'Hz' points
  SCOPE_GAIN / SCOPE_OFFSET    DCV at the applied DC level
  SCOPE_BW SCOPE_TIMEBASE SCOPE_TRIGGER GEN_AMPL GEN_FREQ GEN_OFFSET GEN_FLAT      hand-set (needs a scope-output calibrator or a measuring standard)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import localcontext

import datasheet_builder as db
import dsb_coil
from datasheet_builder import D, DsError, DsProblem, KINDS, fmt

DSB_SCHEMA = 'dsb-1'
ENGINE_OPTIONS = ('function_prompt', 'auto_ramp', 'hv_threshold_v', 'hookup_meter', 'manual_entry')
DEFAULT_OPTIONS = {'function_prompt': True, 'auto_ramp': False, 'hv_threshold_v': 60}
ENGINE_BASE_UNIT = {'degC': 'C', 'ohm': 'ohm'}
STOCK_READY = {'DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP', 'FREQ', 'PERIOD', 'TEMP', 'DIODE', 'CONT', 'SCOPE_GAIN', 'SCOPE_OFFSET'}
HIGH_CURRENT_A = D('2.2')            # above this the hook-up group is the calibrator's high-current output (hookups.py AMP10)


@dataclass
class ExportResult:
    spec: dict = None
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return self.spec is not None


def display_prefix(fn, rng):
    """Prefix symbol the engine displays this range in: the range's, else the function's, else automatic from the full scale (display only)."""
    unit = fn.unit
    if unit in db._NO_PREFIX:
        return ''
    if rng.display_unit:
        return rng.display_unit
    if 'display_prefix' in rng.settings:         # a range of a Cal Processor import: shown in the unit the datasheet prints ('' = the base unit, whatever the size)
        return rng.settings['display_prefix']
    if fn.display_unit:
        return fn.display_unit
    fs = rng.full_scale
    for sym, exp in db._PREFIX_ORDER:           # the smallest prefix that shows the full scale as at most 1000
        if fs / D(10) ** exp <= 1000:
            return sym
    return 'G'


def range_label(fn, rng):
    """'20.0000 V' style: the range's own label, else the full scale in the display unit with the decimals its resolution implies."""
    if rng.label:
        return rng.label
    if rng.settings.get('unspecified'):          # a range the source document does not give (Cal Processor import): nothing to print
        return ''
    prefix = display_prefix(fn, rng)
    factor = db.prefix_factor(prefix)
    with localcontext() as c:
        c.prec = db.PREC
        shown = rng.full_scale / factor
        places = 0
        if rng.resolution is not None:
            r = (rng.resolution / factor).normalize()
            places = max(0, -r.as_tuple().exponent)
    return f'{shown:.{places}f} {prefix}{db.unit_symbol(fn.unit)}'.rstrip()


def _pad_places(text, places):
    """A limit text filled out with zeros to `places` decimals (never shortened): '329.1' -> '329.10'.  Used for points that carry settings['decimals']."""
    if not places:
        return text
    whole, _, frac = text.partition('.')
    return text if len(frac) >= places else f'{whole}.{frac.ljust(places, "0")}'


def _disp(value, factor):
    with localcontext() as c:
        c.prec = db.PREC
        return fmt(value / factor)


def _group(fn, p):
    k = fn.kind
    if k in ('DCI', 'ACI'):
        return 'AMP10' if abs(p.nominal) > HIGH_CURRENT_A else 'UAMP'
    if k == 'TEMP':
        return 'TEMP'
    return 'VOHM'


def _setup_text(fn, p, rng):
    s = fn.settings
    bits = []
    freq = f' at {db.format_si(p.frequency, "Hz")}' if p.frequency is not None else ''
    k = fn.kind
    if fn.direction == 'source' or KINDS[k]['family'] == 'generator':
        wave = p.settings.get('waveform') or s.get('waveform') or ''
        load = p.settings.get('load') or s.get('load') or ''
        bits.append(f'Set the unit under test to output {db.format_si(p.nominal, fn.unit)}{freq}' + (f', {wave}' if wave else '') +
                    (f', load {load}' if load else '') + '.')
        bits.append('Read the measuring standard and type its reading.')
    elif k == 'SCOPE_BW':
        bits.append(f'Apply a leveled sine of {db.format_si(p.amplitude, "V")} p-p, first at the reference frequency, then{freq}. '
                    f'Type the response relative to the reference, in dB.')
    elif k == 'SCOPE_TIMEBASE':
        bits.append(f'Apply a time marker of {db.format_si(p.nominal, "s")} and type the period the scope measures.')
    elif k == 'SCOPE_TRIGGER':
        bits.append(f'Apply {db.format_si(p.amplitude, "V")} p-p{freq} and check the trigger is stable.')
    elif k == 'OHM4':
        bits.append('4-wire connection: connect the sense leads as well.')
    for key in ('vscale', 'hscale', 'coupling', 'impedance'):
        if key in p.settings:
            bits.append(f'{key}: {p.settings[key]}.')
    if p.note:
        bits.append(p.note)
    return ' '.join(bits)


def _engine_step(ds, fn, fi, n, p, rng, lims, period):
    """The handheld-engine step dict (+ nothing else) for one point."""
    k, unit = fn.kind, fn.unit
    lim = lims[period]
    prefix = display_prefix(fn, rng)
    factor = db.prefix_factor(prefix)
    base = ENGINE_BASE_UNIT.get(unit, unit)
    step = dict(table=str(fi), step=n, section=fn.name, switch=fn.switch or KINDS[k]['switch'], range=range_label(fn, rng), models=[ds.model])
    disp_unit = f'{prefix}{db.unit_symbol(unit)}'
    manual = bool(ds.options.get('manual_entry'))          # a manual calibration: nothing is sourced or read by the program, every reading is typed
    ready = k in STOCK_READY and not manual
    nominal = float(p.nominal)
    if KINDS[k].get('passfail') and (k != 'CONT' or manual):
        # p.label (the text of the source document, Cal Processor import) words the question when there is one; otherwise as always
        step.update(kind='VISUAL', test='visual', title=f'{fn.name}: {p.label or range_label(fn, rng)}', question=f'{p.label or fn.name} passes at this point.',
                    setup_key='NONE', setup=_setup_text(fn, p, rng), id=p.id)
        return step, False
    step.update(display_unit=disp_unit, factor=float(factor), base_unit=base)
    if k == 'CONT':
        step.update(kind='OHM', test='beeper', expect=p.settings.get('expect', 'on'), applied=dict(value=nominal, frequency=None), nominal=nominal,
                    question='The beeper is ON (sounding).' if p.settings.get('expect', 'on') == 'on' else 'The beeper is OFF (silent).', id=p.id)
        step['group'] = 'VOHM'
        return step, True
    places = int(p.settings.get('decimals') or 0)         # the point's printed resolution (Cal Processor import): the limits carry its decimals, so typed readings are padded to it
    step.update(low=_pad_places(_disp(lim.low, factor), places), high=_pad_places(_disp(lim.high, factor), places), test='numeric', nominal=nominal)
    if ready:
        if k in ('FREQ', 'PERIOD'):
            freq = p.nominal if k == 'FREQ' else (D(1) / p.nominal)
            step.update(kind='ACV', applied=dict(value=float(p.amplitude), frequency=float(freq)))
            if p.settings.get('waveform') == 'square':                       # a Vpp level: the calibrator makes a square wave of that peak-to-peak amplitude (never a sine)
                step['applied']['waveform'] = 'square'
        elif k in ('DCV', 'DIODE', 'SCOPE_GAIN', 'SCOPE_OFFSET'):
            step.update(kind='DCV', applied=dict(value=nominal, frequency=None))
        elif k in ('OHM2', 'OHM4'):
            step.update(kind='OHM', applied=dict(value=nominal, frequency=None))
        elif dsb_coil.is_coil(fn, p):                                       # clamp meter on the 50-turn coil: the calibrator sources nominal / 50, the meter reads nominal
            out = float(dsb_coil.sourced(p.nominal))
            step.update(kind=k, applied=dict(value=out, frequency=None if p.frequency is None else float(p.frequency)),
                        coil=dsb_coil.TURNS, unc_standard=dsb_coil.MODEL, unc_nominal=nominal)      # unc_*: the keys the Fluke 374 / 375 / 376 steps carry (NOTES.md, standing coil rule)
        else:
            step.update(kind=k, applied=dict(value=nominal, frequency=None if p.frequency is None else float(p.frequency)))
        step['group'] = dsb_coil.group_for(step['applied']['value']) if step.get('coil') else _group(fn, p)
    else:
        step.update(kind='NONE', group='NONE', setup_key='NONE', setup=_setup_text(fn, p, rng))
    step['id'] = p.id
    if fn.settle is not None:
        step['settle'] = fn.settle
    text = _setup_text(fn, p, rng)
    if ready and step.get('coil'):
        text = (dsb_coil.describe(fn, p) + ' ' + text).strip()
    if ready and text:
        step['note'] = text
    return step, ready


def export_spec(ds, period=None, plan=None, uid=None, include_datasheet=True):
    """The runnable spec for `ds` (limits shown for `period`, default ds.default_period).  `plan` = a datasheet_builder_match.MatchResult (or anything
    with .assignments {point id: obj with .to_dict()}) to record each point's chosen standard.  Disabled points are left out.  Any validation
    error, one-sided limit without a bound, or point the schema cannot hold gives spec=None with the problems; nothing is corrected."""
    problems = [p for p in db.validate(ds)]
    res = ExportResult(problems=problems)
    period = period or ds.default_period
    if period not in ds.period_ids():
        problems.append(DsProblem('default_period', f'Period {period!r} is not defined in this datasheet.'))
    if db.errors(problems):
        return res
    steps, ready_n, hand = [], 0, 0
    for fi, fn in enumerate(ds.functions, 1):
        n = 0
        for p in fn.points:
            if not p.enabled:
                continue
            rng = fn.range(p.range_id)
            nolimit = bool(KINDS[fn.kind].get('passfail'))
            lims, skip = {}, False
            for per in ds.period_ids():
                if nolimit:
                    lims[per] = db.Limit(p.nominal, None, None)
                    continue
                lims[per] = fn.limit_for(p, per, ds)
                if lims[per].low is None or lims[per].high is None:
                    skip = True
                    problems.append(DsProblem('one_sided_needs_bound', f'Point {p.id} [{per}]: the runnable spec needs both limits; give the one-sided entry a bound.',
                                              where=p.id))
            if skip:
                continue
            n += 1
            step, ready = _engine_step(ds, fn, fi, n, p, rng, lims, period)
            ready_n += ready
            hand += not ready
            lim = lims[period]
            step['ref'] = f'{ds.title or ds.model} v{ds.version}'
            printed = next(iter(fn.governing(p) or [None]), None)
            if printed is not None:
                text = printed.printed.get(period) or printed.exprs[period].text(fn.unit) if period in printed.exprs else ''
                if text:
                    step['accuracy'] = text
                tt = fn.tol_text(p, period, ds)
                if tt:
                    step['tol_text'] = tt
            step['dsb'] = {
                'function': fn.id, 'kind': fn.kind, 'direction': fn.direction, 'point_id': p.id, 'range_id': p.range_id, 'unit': fn.unit,
                'engine_ready': ready,
                'stimulus': {'nominal': fmt(p.nominal), 'frequency': fmt(p.frequency) if p.frequency is not None else None,
                             'amplitude': fmt(p.amplitude) if p.amplitude is not None else None, 'settings': {**fn.settings, **p.settings}},
                'limit': {'nominal': fmt(lim.nominal), 'low': fmt(lim.low) if lim.low is not None else None,
                          'high': fmt(lim.high) if lim.high is not None else None,
                          'minus': fmt(lim.minus) if lim.minus is not None else None, 'plus': fmt(lim.plus) if lim.plus is not None else None,
                          'source': lim.source, 'one_sided': lim.one_sided,
                          'periods': {per: {'low': fmt(l.low) if l.low is not None else None, 'high': fmt(l.high) if l.high is not None else None}
                                      for per, l in lims.items()}}}
            if p.label:                                  # the source document's own text for the nominal (Cal Processor import); written only when set
                step['dsb']['label'] = p.label
            a = _assignment(ds, plan, p.id)
            if a:
                step['dsb']['assignment'] = a
            steps.append(step)
    if db.errors(problems):
        return res
    models = {ds.model: {'name': f'{ds.make} {ds.model}'.strip(), 'brand': ds.make, 'model_note': ds.title}}
    options = dict(DEFAULT_OPTIONS)
    options.update({k: v for k, v in ds.options.items() if k in ENGINE_OPTIONS})
    notes = []
    if ds.options.get('manual_entry'):
        notes.append(f'Manual calibration: all {hand + ready_n} points are typed by the technician (no instrument is driven by the program).')
    elif hand:
        notes.append(f'{hand} of {hand + ready_n} points are hand-set in the stock handheld engine (scope / generator functions need the runtime stage).')
    spec = {
        'schema': 2, 'kind': 'manual-reading', 'user_built': True, 'options': options,
        'source': {'document': ds.source.get('document') or f'{ds.make} {ds.model} - user-built datasheet "{ds.title}"',
                   'pages': ds.source.get('pages', ''),
                   'note': (ds.source.get('note') or '') + (' ' if ds.source.get('note') else '') +
                           (f'Manual calibration (Datasheet Builder), version {ds.version}. Limits are the typed limits of each point; compare them with the source datasheet. '
                            f'Period shown: {period}.' if ds.options.get('manual_entry') else
                            f'User-built datasheet (Datasheet Builder), version {ds.version}. Limits are calculated from the specification the author entered; '
                            f'compare them with the manufacturer\'s document. Period shown: {period}.')},
        'models': models, 'steps': steps,
        'dsb': {'schema': DSB_SCHEMA, 'uid': uid or ds.uid, 'version': ds.version, 'revision': ds.revision, 'title': ds.title, 'make': ds.make,
                'model': ds.model, 'exported_at': datetime.now().isoformat(timespec='seconds'), 'period': period,
                'periods': [p.to_dict() for p in ds.periods], 'default_period': ds.default_period,
                'engine': {'stock_runnable': hand == 0, 'points': len(steps), 'runnable': ready_n, 'hand_set': hand, 'notes': notes}},
    }
    if ds.options.get('generated'):                        # a procedure made by the Procedure Generator: the run window and the report read its DRAFT / approved state (generated_draft.py)
        spec['dsb']['generated'] = ds.options['generated']
    if any(s.get('coil') for s in steps):                  # the cable-change text of the coil rows (the 376 jaw wording); the engine reads spec['groups'][step.group]
        spec['groups'] = {g: v for g, v in dsb_coil.groups().items() if any(s.get('group') == g for s in steps)}
    if include_datasheet:
        spec['dsb']['datasheet'] = ds.to_dict()
    if plan is not None and hasattr(plan, 'to_dict'):
        spec['dsb']['plan'] = plan.to_dict()
    res.spec, res.notes = spec, notes
    return res


def _assignment(ds, plan, pid):
    if plan is not None and getattr(plan, 'assignments', None) and pid in plan.assignments:
        a = plan.assignments[pid]
        return a.to_dict() if hasattr(a, 'to_dict') else dict(a)
    if pid in ds.assignments:
        return {'standard': ds.assignments[pid], 'mode': 'override'}
    return None


def datasheet_from_spec(spec):
    """The Datasheet a spec carries in spec['dsb']['datasheet'], or None when it has none or it is damaged."""
    try:
        return db.Datasheet.from_dict(spec['dsb']['datasheet'])
    except (KeyError, TypeError, DsError):
        return None


def validate_spec_ext(spec):
    """Problems in the 'dsb' extension of a spec (empty list when the spec has none).  Called by procspec.validate_manual_reading."""
    out = []

    def add(code, msg, level='error', where=''):
        out.append(DsProblem(code, msg, level, where))

    head = spec.get('dsb')
    steps_with = [s for s in spec.get('steps', []) if 'dsb' in s]
    if head is None:
        if steps_with:
            add('dsb_header', 'Steps carry dsb data but the spec has no top-level dsb header.')
        return out
    if not isinstance(head, dict) or head.get('schema') != DSB_SCHEMA:
        add('dsb_schema', f'dsb.schema must be {DSB_SCHEMA!r}.', where='dsb')
        return out
    if head.get('period') not in [p.get('id') for p in head.get('periods', [])]:
        add('dsb_period', 'dsb.period is not one of dsb.periods.', where='dsb')
    ids = [s.get('id') for s in spec.get('steps', [])]
    if len(set(ids)) != len(ids):
        add('dup_point_id', 'Two steps have the same id.', where='steps')
    for s in steps_with:
        d, w = s['dsb'], str(s.get('id'))
        if d.get('point_id') != s.get('id'):
            add('dsb_point_id', 'dsb.point_id must equal the step id.', where=w)
        if d.get('kind') not in KINDS:
            add('bad_kind', f"dsb.kind {d.get('kind')!r} is not a datasheet function kind.", where=w)
        if d.get('direction') not in db.DIRECTIONS:
            add('bad_direction', 'dsb.direction must be measure or source.', where=w)
        if not isinstance(d.get('engine_ready'), bool):
            add('dsb_engine_ready', 'dsb.engine_ready must be true or false.', where=w)
        lim = d.get('limit') or {}
        try:
            low = db.dec(lim['low']) if lim.get('low') is not None else None
            high = db.dec(lim['high']) if lim.get('high') is not None else None
            if low is not None and high is not None and low > high:
                add('limit_inverted', 'dsb.limit.low is above dsb.limit.high.', where=w)
            for per, pl in (lim.get('periods') or {}).items():
                lo = db.dec(pl['low']) if pl.get('low') is not None else None
                hi = db.dec(pl['high']) if pl.get('high') is not None else None
                if lo is not None and hi is not None and lo > hi:
                    add('limit_inverted', f'dsb.limit.periods[{per}] is inverted.', where=w)
        except (DsError, KeyError, TypeError):
            add('dsb_limit', 'dsb.limit holds a value that is not a number.', where=w)
    ds = head.get('datasheet')
    if ds is not None:
        try:
            sheet = db.Datasheet.from_dict(ds)
            have = {p.id for _, p in sheet.all_points()}
            for s in steps_with:
                if s['dsb'].get('point_id') not in have:
                    add('dsb_orphan', 'A step names a point that is not in the embedded datasheet.', 'warn', str(s.get('id')))
        except DsError as e:
            add('dsb_datasheet', f'The embedded datasheet cannot be read: {e}', where='dsb.datasheet')
    return out
