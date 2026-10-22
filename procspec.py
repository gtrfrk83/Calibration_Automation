"""Loader for performance-verification specs (specs/*.json).

A spec is the machine-readable form of a manufacturer's performance-verification tables: every test
point with its range, input, and the published limit for each time period, plus the manual page it
came from.  Procedures import POINTS from here instead of hard-coding limits, so a new model is
mostly a new JSON file.  See specs/README.txt for the schema.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

import cmdreg

UNITS = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM2': 'ohm', 'OHM4': 'ohm', 'FREQ': 'Hz', 'CAP': 'F'}
NAMES = {'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current', 'ACI': 'AC current',
         'OHM2': '2-wire ohms', 'OHM4': '4-wire ohms', 'FREQ': 'Frequency', 'CAP': 'Capacitance'}


class SpecError(ValueError):
    pass


def _fmt(value, unit):
    from ui_theme import si_one
    number, symbol = si_one(value, unit)
    return f'{number} {symbol}'


MANUAL_KINDS = ('manual-reading', 'handheld-manual')


def load(path) -> dict:
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec.get('kind') in MANUAL_KINDS:              # handheld (manual-reading) specs, incl. user-built datasheets: their own checks
        bad = [p for p in validate_manual_reading(spec) if getattr(p, 'level', 'error') == 'error']
        if bad:
            raise SpecError('; '.join(str(p) for p in bad[:5]))
        return spec
    validate(spec)
    return spec


class SpecProblem(cmdreg.Problem):
    """A finding about a spec file: str message, .code, .level ('error' | 'warn'), .where."""
    level = 'error'
    where = ''

    def __new__(cls, code, message, level='error', where=''):
        obj = super().__new__(cls, code, message)
        obj.level, obj.where = level, where
        return obj


_TESTS = ('numeric', 'beeper', 'visual')


def validate_manual_reading(spec: dict) -> list:
    """Problems in a handheld 'manual-reading' spec (schema 2 / 3: steps[], models{}, options{}) as handheld_dmm.points_for() and the engine use it.
    Pure; returns [SpecProblem] and never raises.  The additive 'dsb' extension written by the Datasheet Builder (datasheet_builder_specs.py)
    is validated too when present.  The shipped Fluke / Klein specs pass this check unchanged."""
    out = []

    def add(code, msg, level='error', where=''):
        out.append(SpecProblem(code, msg, level, where))

    try:
        if spec.get('kind') not in MANUAL_KINDS:
            add('kind', "kind must be 'manual-reading' (or the older 'handheld-manual').")
        if not isinstance(spec.get('models'), dict) or not spec.get('models'):
            add('models', 'models{} is missing or empty.')
        if not isinstance(spec.get('options', {}), dict):
            add('options', 'options must be an object.')
        steps = spec.get('steps')
        if not isinstance(steps, list) or not steps:
            add('steps', 'steps[] is missing or empty.')
            steps = []
        seen = set()
        for i, s in enumerate(steps, 1):
            w = str(s.get('id', f'step {i}')) if isinstance(s, dict) else f'step {i}'
            if not isinstance(s, dict):
                add('step', 'a step is not an object.', where=w)
                continue
            for key in ('id', 'table', 'step', 'section', 'switch', 'range', 'models', 'kind', 'test'):
                if key not in s:
                    add('step_key', f'step is missing {key!r}.', where=w)
            if s.get('id') in seen:
                add('dup_id', f"step id {s.get('id')!r} is used twice.", where=w)
            seen.add(s.get('id'))
            if s.get('test') not in _TESTS:
                add('test', f"test must be one of {_TESTS}.", where=w)
            if isinstance(spec.get('models'), dict) and isinstance(s.get('models'), list):
                for m in s['models']:
                    if m not in spec['models']:
                        add('model_unknown', f'step names model {m!r}, which models{{}} does not define.', where=w)
            if s.get('test') == 'numeric':
                for key in ('display_unit', 'factor', 'base_unit', 'low', 'high', 'nominal'):
                    if key not in s:
                        add('step_key', f'numeric step is missing {key!r}.', where=w)
                try:
                    if not float(s['factor']) > 0:
                        add('factor', 'factor must be above zero.', where=w)
                    if Decimal(str(s['low'])) > Decimal(str(s['high'])):
                        add('limit_inverted', 'low is above high.', where=w)
                except (KeyError, InvalidOperation, ValueError, TypeError):
                    add('limit_value', 'low / high / factor are not numbers.', where=w)
            elif s.get('test') == 'beeper' and not (s.get('applied') and s.get('expect')):
                add('step_key', 'beeper step needs applied and expect.', where=w)
        if spec.get('dsb') is not None or any(isinstance(s, dict) and 'dsb' in s for s in steps):
            import datasheet_builder_specs
            out.extend(datasheet_builder_specs.validate_spec_ext(spec))
    except Exception as e:                                # a validator must never take the program down
        add('validator', f'could not check the spec ({type(e).__name__}: {e})')
    return out


def validate(spec: dict):
    periods = spec['periods']
    seen = 0
    for s in spec['sections']:
        for p in s['points']:
            seen += 1
            where = f"{s['id']} point {seen}"
            if p['kind'] not in UNITS:
                raise SpecError(f'{where}: unknown kind {p["kind"]!r}')
            if set(p['limits']) != set(periods) or any(not v > 0 for v in p['limits'].values()):
                raise SpecError(f'{where}: limits must be positive for every period {periods}')
            if p['kind'] in ('ACV', 'ACI') and not p.get('frequency'):
                raise SpecError(f'{where}: AC point needs a frequency')
    if spec['default_period'] not in periods:
        raise SpecError('default_period is not one of periods')


def flatten(spec: dict) -> list[dict]:
    """One flat, numbered list of points (ids start at 1) in the manual's order."""
    points = []
    for s in spec['sections']:
        for raw in s['points']:
            p = dict(raw)
            p['id'] = len(points) + 1
            p['section'] = s['id']
            p['section_title'] = s['title']
            p['page'] = s['page']
            p['source'] = s.get('source', 'calibrator')
            p['optional'] = bool(s.get('optional'))
            p['setup'] = s['setup']
            p['terminal'] = p.get('terminal') or s.get('terminal') or 'FRONT'
            p['unit'] = UNITS[p['kind']]
            p['description'] = describe(p)
            points.append(p)
    return points


def describe(p: dict) -> str:
    name = NAMES[p['kind']]
    if p['source'] == 'none':
        what = 'input open' if p.get('input') == 'open' else 'input shorted'
        return f"{p['terminal'].title()} {name}, {_fmt(p['range'], p['unit'])} range ({what})"
    if p['kind'] == 'FREQ':
        return f"Frequency {_fmt(p['nominal'], 'Hz')} at {_fmt(p['amplitude'], 'V')} rms, {_fmt(p['range'], 'V')} range"
    text = f"{name} {_fmt(p['nominal'], p['unit'])}"
    if p.get('frequency'):
        text += f" @ {_fmt(p['frequency'], 'Hz')}"
    text += f", {_fmt(p['range'], p['unit'])} range"
    if p.get('filter_hz'):
        text += f", {p['filter_hz']:g} Hz filter"
    return text


def apply_period(points: list[dict], period: str):
    """Set each point's 'error' (the allowed +/- error from nominal) from the chosen period."""
    for p in points:
        p['error'] = float(f"{p['limits'][period]:.9g}")


def wiring_key(p: dict) -> tuple:
    """Points with the same key can run back-to-back with no rewiring prompt."""
    if p['source'] == 'none':
        return ('ZERO', p['terminal'], p['input'])
    if p['source'] == 'manual':
        return ('MANUAL', p['kind'])
    group = 'CURRENT' if p['kind'] in ('DCI', 'ACI') else 'RES4' if p['kind'] == 'OHM4' else 'RES2' if p['kind'] == 'OHM2' else 'VOLT'
    return (p['source'], p['terminal'], group)
