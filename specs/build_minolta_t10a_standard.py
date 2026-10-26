"""Builds specs/standards/minolta_t10a_standard.json: the Minolta T-10A illuminance meter (the lab's white-light standard, asset ATS-04959) plus a flat 5 % black light row.

    python specs/build_minolta_t10a_standard.py

SOURCE (white light): the owner's SpecTrack tree for 'Minolta T-10A Illumination meter' (screenshot supplied 2026-10-26), one period '1 yr', ID ATS-04959:
    Light [fc]:  0.000-2.999 +0.001 fc | 3.00-29.99 +0.01 | 30.0-299.9 +0.1 | 300-2999 +1 | 3000-29990 +10      each  +/-(2 % I.V. + term)
    Light [lx]:  0.00-29.99 +0.01 lx | 30.0-299.9 +0.1 | 300-2999 +1 | 3000-29990 +10 | 30000-299900 +100     each  +/-(2 % I.V. + term)
The numbers were read from the image twice.  The units are stored as the suite's own 'FC' and 'lux' (kinds FC / LUX), nothing converted.
Black light: the owner said 'a flat 5 %': +/-(5 % I.V.), no fixed term, one row.  The range is NOT given by the owner; 0 to 3000 uW/cm2 at 365 nm is
taken from the A2LA scope row (specs/build_light_standard.py) and flagged as an assumption in the sheet.
No confidence level is printed (divisor 2, laboratory convention).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402

# (function, unit, printed unit, [(range lo text, range hi text, fixed term text)])
WHITE = [
    ('Light [White] (FC)', 'FC', [('0', '2.999', '0.001'), ('3', '29.99', '0.01'), ('30', '299.9', '0.1'), ('300', '2999', '1'), ('3000', '29990', '10')]),
    ('Light [White] (lux)', 'lux', [('0', '29.99', '0.01'), ('30', '299.9', '0.1'), ('300', '2999', '1'), ('3000', '29990', '10'), ('30000', '299900', '100')]),
]
BLACK = ('Light [Black @ 365 nm] (uW/cm2)', 'uW/cm2', '0', '3000')

NOTES = {
    '1': 'SOURCE: the owner\'s SpecTrack tree for the Minolta T-10A Illumination meter (asset ATS-04959), read from a screenshot on 2026-10-26: 1 yr accuracy +/-(2 % I.V. + a fixed term) '
         'in five ranges in fc and five in lx. Built by specs/build_minolta_t10a_standard.py.',
    '2': 'PERCENTAGE: "I.V." is the indicated value (the reading); the fixed term is added to 2 % of the reading in that range, in the range\'s own unit (fc or lx). Nothing is converted between fc and lx.',
    '3': 'BLACK LIGHT: the owner specified a flat 5 % (+/-(5 % I.V.), no fixed term). The range 0 to 3000 uW/cm2 at 365 nm is ASSUMED from the A2LA scope row (not given by the owner). UNVERIFIED: '
         'the black light meter, its wavelength and its range; change the range in the builder if it differs.',
    '4': 'CONFIDENCE: no level is printed; stored with no level (divisor 2, laboratory convention). One period, "1 yr", as in the tree. Not stored: resolution, stability, spectral mismatch, '
         'cosine response and temperature terms (not in the tree).',
    '5': 'NOT TO BE CONFUSED WITH A2LA-LIGHT: that sheet is the lab\'s own scope CMC (2.9 % white, 5 % black). This sheet is the working standard instrument\'s accuracy. Nothing selects it yet: '
         'a procedure or the uncertainty tools use it only when it is chosen as the standard for a light point.',
}
LIMITS = [dict(function='Light [White]', limit='+/-(2 % I.V. + 0.001 fc ... 10 fc); +/-(2 % I.V. + 0.01 lx ... 100 lx); five ranges each.', page=''),
          dict(function='Light [Black @ 365 nm]', limit='+/-(5 % I.V.), flat; range 0 to 3000 uW/cm2 assumed.', page='')]


def make_range(name, unit, lo, hi, term):
    param = sm.parse_param(f'{lo} {unit} to {hi} {unit}')
    spec = sm.parse_spec(f'[1 yr] Accuracy: +/-(2 % I.V. + {term} {unit})')
    if param is None or spec.get('error'):
        raise ValueError(f'{name}: {lo}-{hi} {unit}')
    kind, variant = sm.classify(name)
    return dict(label=f'{lo} to {hi} {unit}', page=0, params=[param], specs=[spec], raw_other=[], printed=f'{lo} to {hi} {unit}', kind=kind, variant=variant,
                amp_lo=param['lo'], amp_hi=param['hi'], unit=param['unit'], freq_lo=None, freq_hi=None, qualifiers=[], range_max=None, resolution=None, res_src='')


def make_black():
    name, unit, lo, hi = BLACK
    param = sm.parse_param(f'{lo} {unit} to {hi} {unit}')
    spec = sm.parse_spec('[1 yr] Accuracy: +/-(5 % I.V.)')
    if param is None or spec.get('error'):
        raise ValueError('black light')
    spec['rel'] = 0.05
    kind, variant = sm.classify(name)
    return dict(label=f'{lo} to {hi} {unit}', page=0, params=[param], specs=[spec], raw_other=[], printed=f'{lo} to {hi} uW/cm2 (range assumed)', kind=kind, variant=variant,
                amp_lo=param['lo'], amp_hi=param['hi'], unit=param['unit'], freq_lo=None, freq_hi=None, qualifiers=[], range_max=None, resolution=None, res_src='')


def build():
    functions = [dict(name=name, direction='output', page=0, ranges=[make_range(name, unit, *r) for r in rows]) for name, unit, rows in WHITE]
    functions.append(dict(name=BLACK[0], direction='output', page=0, ranges=[make_black()]))
    data = dict(schema=1, standard=dict(
        manufacturer='Minolta', model='T-10A', description='Illuminance meter (white light) and black light, working standard ATS-04959',
        confidence_text='no confidence level printed (divisor 2, laboratory convention)', confidence_pct=None,
        reference='SpecTrack tree, Minolta T-10A Illumination meter, ID ATS-04959 (owner screenshot 2026-10-26)', revision='', author='written by specs/build_minolta_t10a_standard.py',
        approved_by='', approve_date='', source_pdf='', sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes=NOTES, limits=LIMITS, functions=functions)
    probs = list(sm.validate_data(data))
    probs.append(dict(level='warn', where='Light [Black @ 365 nm]', what='Flat 5 % given by the owner; the 0 to 3000 uW/cm2 range is assumed from the A2LA scope. UNVERIFIED.'))
    probs.append(dict(level='warn', where='standard', what='No confidence level printed: divisor 2 (laboratory convention). Read from a screenshot, not a manufacturer document.'))
    data['problems'] = probs
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'minolta_t10a_standard.json'
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"T-10A: {len(data['functions'])} functions, {sum(len(f['ranges']) for f in data['functions'])} ranges -> {out}")
    for p in data['problems']:
        print(p['level'].upper(), p['where'], '-', p['what'])


if __name__ == '__main__':
    main()
