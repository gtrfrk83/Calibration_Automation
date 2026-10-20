"""Loader for performance-verification specs (specs/*.json).

A spec is the machine-readable form of a manufacturer's performance-verification tables: every test
point with its range, input, and the published limit for each time period, plus the manual page it
came from.  Procedures import POINTS from here instead of hard-coding limits, so a new model is
mostly a new JSON file.  See specs/README.txt for the schema.
"""
from __future__ import annotations

import json
from pathlib import Path

UNITS = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM2': 'ohm', 'OHM4': 'ohm', 'FREQ': 'Hz', 'CAP': 'F'}
NAMES = {'DCV': 'DC volts', 'ACV': 'AC volts', 'DCI': 'DC current', 'ACI': 'AC current',
         'OHM2': '2-wire ohms', 'OHM4': '4-wire ohms', 'FREQ': 'Frequency', 'CAP': 'Capacitance'}


class SpecError(ValueError):
    pass


def _fmt(value, unit):
    from ui_theme import si_one
    number, symbol = si_one(value, unit)
    return f'{number} {symbol}'


def load(path) -> dict:
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    validate(spec)
    return spec


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
