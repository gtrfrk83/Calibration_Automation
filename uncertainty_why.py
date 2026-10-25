"""'Why is there no uncertainty?' for a review-window row the lab scope does not cover, and the quickest ways to fix it.  Toolkit-free.

    d = uncertainty_why.diagnose(model, idx)        # Diagnosis(reasons, suggestions, hints)
    d.reasons      [(kind, title, text)]  kind 'missing' | 'ok' | 'hint'
    d.suggestions  [Suggestion(label, text, source, detail)]   best first; `text` is what Row.set_typed takes (e.g. '0.012 dB')

The suggestions only ever fill a row that is NOT in scope (Row.can_type); a row the scope covers is never overridden, and a typed value is never compared
down against a CMC because there is none.  Order: the standard's own specification (k = 2), then what was used last time for this point, then a saved
'all points like this' rule.  The calculator is the window's own last option.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import report_review_model as M

KIND_NAMES = {'DCV': 'DC voltage', 'ACV': 'AC voltage', 'DCI': 'DC current', 'ACI': 'AC current', 'OHM': 'resistance', 'OHM2': 'resistance', 'OHM4': 'resistance',
              'CAP': 'capacitance', 'FREQ': 'frequency', 'TEMP': 'temperature', 'FLAT': 'RF flatness', 'LFFLAT': 'low-frequency flatness', 'ACAMP': 'AC amplitude',
              'TIMEBASE': 'time base'}


@dataclass
class Suggestion:
    label: str          # button text: 'Use 0.012 dB'
    text: str           # what goes into Row.set_typed
    source: str         # recorded with the value: 'Fluke 5790B specification (k = 2)' / 'Same as last time' / 'Saved rule'
    detail: str = ''    # one line under the button


@dataclass
class Diagnosis:
    reasons: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)


def _freq_text(f):
    if not f:
        return ''
    import ui_theme_core as ui
    n, s = ui.si_one(f, 'Hz')
    return f' at {n} {s}'


def _display(value_si, row) -> str:
    """An SI value as the text the row's entry takes, in the unit the grid shows (rounded UP to 2 figures, k = 2)."""
    import uncertainty
    v = uncertainty.round_up(value_si)
    scale, sym = M.entry_scale(row.spec, row.cur)
    shown = v / float(scale)
    txt = f'{shown:.6g}'
    return f'{txt} {sym}'.strip()


def diagnose(model, idx) -> Diagnosis:
    row = model.rows[idx]
    spec, cur = row.spec, row.cur
    q = spec.q or {}
    d = Diagnosis()
    what = KIND_NAMES.get(str(q.get('kind', '')), 'this kind of point')
    where = f"{spec.nominal_text}{_freq_text(q.get('frequency'))}".strip()
    if cur.cmc is None:
        d.reasons.append(('missing', 'Lab scope (A2LA)', f'No line of the lab scope covers {what} at {where}, so there is no accredited minimum for this point.'))
    else:
        d.reasons.append(('ok', 'Lab scope (A2LA)', f'Covered: scope minimum {M.fmt(cur.cmc, cur.unit)}.'))
    std = row.standard
    if cur.budget is None:
        who = M.label(std) if std else (spec.std_label or 'the standard used')
        d.reasons.append(('missing', 'Standard', f'{who} has no specification row loaded for this point (Standards Specs), so no budget can be worked out.'))
    else:
        d.reasons.append(('ok', 'Standard', f'{M.label(std) or spec.std_label or "Standard"} specification: {M.fmt(cur.budget, cur.unit)} (k = 2).'))
    for hint in getattr(spec, 'hints', None) or []:
        d.reasons.append(('hint', 'Hint', hint))
    try:                                                            # another standard the sheets offer that the scope covers
        for k in model.options(idx):
            if k == std:
                continue
            ev = M.evaluate(spec, k)
            if ev.cmc is not None:
                d.reasons.append(('hint', 'Hint', f'With the {M.label(k)} this point is in scope: choose it in the Standard column.'))
                break
    except Exception:
        pass
    if not row.can_type():
        return d
    if cur.budget is not None:
        t = _display(cur.budget, row)
        d.suggestions.append(Suggestion(f'Use {t}', t, f'{M.label(std) or spec.std_label or "Standard"} specification (k = 2)',
                                        'From the standard\'s published specification, rounded up to 2 figures.'))
    try:
        import uncertainty_fixes as F
        proc = model.procedure or model.title
        last = F.last_fix(proc, spec.section, spec.description, cur.unit)
        if last and not any(s.text == last['text'] for s in d.suggestions):
            d.suggestions.append(Suggestion(f'Use {last["text"]} (same as last time)', last['text'], 'Same as last time',
                                            f'Used {last["at"]}' + (f' by {last["who"]}' if last['who'] else '') + (f': {last["source"]}' if last['source'] else '')))
        rule = F.like_rule(proc, spec.section, cur.unit)
        if rule and not any(s.text == rule['text'] for s in d.suggestions):
            d.suggestions.append(Suggestion(f'Use {rule["text"]} (rule for points like this)', rule['text'], 'Saved rule',
                                            f'Saved {rule["at"]}' + (f' by {rule["who"]}' if rule['who'] else '') + (f': {rule["source"]}' if rule['source'] else '')))
    except Exception:
        pass
    return d


def like_rows(model, idx) -> list:
    """Indexes of the other rows 'like' this one: same section and unit, not in scope and not yet typed."""
    r0 = model.rows[idx]
    return [i for i, r in enumerate(model.rows) if i != idx and r.spec.section == r0.spec.section and r.cur.unit == r0.cur.unit and r.can_type() and r.typed is None]


def apply(model, idx, text, source, reason='', like=False, who=''):
    """Type `text` into row idx (and the rows like it when `like`), remember it.  Returns (ok, message, rows changed)."""
    ok, msg = model.set_typed(idx, text, source=source, reason=reason)
    if not ok:
        return False, msg, 0
    changed = 1
    if like:
        for i in like_rows(model, idx):
            if model.set_typed(i, text, source=source, reason=reason)[0]:
                changed += 1
    try:
        import uncertainty_fixes as F
        r = model.rows[idx]
        F.save_fix(model.procedure or model.title, r.spec.section, r.spec.description, r.cur.unit, text, source, reason, who, like=like)
    except Exception:
        pass
    return True, '', changed


def apply_saved_rules(model, who='') -> int:
    """When the window opens: rows not in scope that a saved 'all points like this' rule covers get it (shown as typed, with the rule as the source)."""
    n = 0
    try:
        import uncertainty_fixes as F
    except Exception:
        return 0
    proc = model.procedure or model.title
    for i, r in enumerate(model.rows):
        if r.typed is not None or not r.can_type():
            continue
        rule = F.like_rule(proc, r.spec.section, r.cur.unit)
        if rule and model.set_typed(i, rule['text'], source=f'Saved rule ({rule["at"]})', reason=rule.get('reason', ''))[0]:
            n += 1
    return n
