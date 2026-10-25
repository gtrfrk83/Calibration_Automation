"""Datasheet Builder: what changed between two versions of a datasheet.

compare(old, new) -> Diff(header=[lines], rows=[Change], counts={'added','removed','changed'}).  Pure Python on two Datasheet objects (no Qt, no files):
points are matched by what they test (section, range full scale, nominal, frequency, level), not by id, because a point's id follows its value.
Limits are the exact Decimal limits of Function.limit_for for the datasheet's default period; nothing here changes a datasheet."""
from __future__ import annotations

from dataclasses import dataclass, field

import datasheet_builder as db


@dataclass
class Change:
    kind: str                # 'added' | 'removed' | 'changed'
    section: str
    point: str               # the nominal text of the point ('' for a whole section)
    what: str                # what changed ('limits', 'switched off', 'remark', ...) or '' for added / removed
    before: str = ''
    after: str = ''


@dataclass
class Diff:
    header: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    @property
    def counts(self):
        return {k: sum(1 for r in self.rows if r.kind == k) for k in ('added', 'removed', 'changed')}

    @property
    def same(self):
        return not self.header and not self.rows

    def summary(self):
        if self.same:
            return 'The two versions are the same.'
        c = self.counts
        bits = [f'{n} {k}' for k, n in c.items() if n]
        return (('Header: ' + '; '.join(self.header) + '. ') if self.header else '') + (', '.join(bits) + '.' if bits else '')


def _si(value, unit):
    if value is None:
        return 'open'
    try:
        return db.format_si(value, unit)
    except Exception:
        return str(value)


def _point_text(fn, p):
    s = _si(p.nominal, fn.unit)
    if p.frequency is not None:
        s += ' @ ' + _si(p.frequency, 'Hz')
    if p.amplitude is not None:
        import datasheet_builder_ui_model as M
        s += ', level ' + M.level_display(fn, p)
    return s


def _limits(ds, fn, p):
    if fn.info.get('passfail'):
        return 'pass / fail'
    try:
        lim = fn.limit_for(p, ds.default_period, ds)
    except Exception:
        return 'none'
    if lim is None:
        return 'none'
    return f'{_si(lim.low, fn.unit)} to {_si(lim.high, fn.unit)}'


def _key(fn, p):
    rng = fn.range(p.range_id)
    return (rng.full_scale if rng is not None else None, p.nominal, p.frequency, p.amplitude)


def _fields(ds, fn, p):
    rng = fn.range(p.range_id)
    return {
        'limits': _limits(ds, fn, p),
        'run': 'runs' if p.enabled else 'switched off',
        'remark': p.note or '',
        'resolution': _si(rng.resolution, fn.unit) if rng is not None and rng.resolution is not None else '',
        'waveform': p.settings.get('waveform', ''),
        'other settings': repr(sorted((k, v) for k, v in p.settings.items() if k != 'waveform')) if any(k != 'waveform' for k in p.settings) else '',
    }


def compare(old, new):
    """Everything that differs between two Datasheet objects, older first."""
    d = Diff()
    for label, a, b in (('make', old.make, new.make), ('model', old.model, new.model), ('title', old.title, new.title)):
        if (a or '') != (b or ''):
            d.header.append(f'{label} "{a}" -> "{b}"')
    pa, pb = [x.label or x.id for x in old.periods], [x.label or x.id for x in new.periods]
    if pa != pb:
        d.header.append(f'periods {", ".join(pa)} -> {", ".join(pb)}')
    if old.default_period != new.default_period:
        d.header.append(f'default period {old.default_period} -> {new.default_period}')
    fa = {f.id: f for f in old.functions}
    fb = {f.id: f for f in new.functions}
    for fid, f in fa.items():
        if fid not in fb:
            d.rows.append(Change('removed', f.name, '', 'section', f'{len(f.points)} point(s)'))
    for fid, f in fb.items():
        if fid not in fa:
            d.rows.append(Change('added', f.name, '', 'section', '', f'{len(f.points)} point(s)'))
            continue
        g = fa[fid]
        if g.name != f.name:
            d.rows.append(Change('changed', f.name, '', 'section name', g.name, f.name))
        ma = {_key(g, p): p for p in g.points}
        mb = {_key(f, p): p for p in f.points}
        for k, p in ma.items():
            if k not in mb:
                d.rows.append(Change('removed', f.name, _point_text(g, p), '', _limits(old, g, p)))
        for k, q in mb.items():
            p = ma.get(k)
            if p is None:
                d.rows.append(Change('added', f.name, _point_text(f, q), '', '', _limits(new, f, q)))
                continue
            before, after = _fields(old, g, p), _fields(new, f, q)
            for name in before:
                if before[name] != after[name]:
                    d.rows.append(Change('changed', f.name, _point_text(f, q), name, before[name] or '(none)', after[name] or '(none)'))
    return d
