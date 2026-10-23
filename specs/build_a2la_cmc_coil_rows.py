"""Adds the A2LA scope's coil lines to specs/a2la_1888_03_cmc.json (the lab CMC table read by uncertainty.py), so scope-CMC lookups above 30.2 A are covered.

    python specs/build_a2la_cmc_coil_rows.py            # idempotent: adds the rows once, rewrites the file in the file's own format (json indent 1, ASCII escapes, no final newline)

The CMC table itself has no other builder (it was prepared by hand from the scope); this script ONLY appends, every existing band / range / row is kept byte for byte
(tests/test_a2la_cmc_coil_rows.py compares the old rows by value and by serialised text).  SOURCE (VERIFIED against the rendered page images, each value read twice,
2026-10-23), A2LA cert. 1888.03 rev. 07/07/2026, section V, column header CMC 2, 5, 9 (+/-):
  printed p. 9 of 47, DC Current - Generate, comment 'Transconductance amplifier/coil':  (2 to 20) A 90 uA/A + 0.1 mA;  (20 to 120) A 80 uA/A + 8 mA;  (120 to 3000) A 0.8 % + 0.08 A
  printed p. 30 of 47, AC Current - Generate (cont), comment 'Transconductance amplifier/coil':  (20.5 to 3000) A  (16 to 850) Hz 0.7 % + 0.84 A;  (0.85 to 6) kHz 0.8 % + 0.84 A
  printed p. 30 of 47, 'Clamp-On Only', comment 'Multifunction calibrator/coil':  (20.5 to 1025) A  (45 to 65) Hz 0.8 %;  (65 to 440) Hz 0.99 %
Same figures as specs/build_coil_standard.py (A2LA-5500A-COIL: the five 5500A/COIL lines) and specs/build_current_amp_coil_standard.py (A2LA-CURRENT-AMP-COIL: the two
amplifier/coil AC lines); the clamp-on interaction uncertainty of the coil datasheet is NOT part of any CMC and is not combined into anything here.

Lookup consequence (uncertainty.Scope.dmm: overlapping bands use the LARGER CMC, closed intervals): a DCI point of 2 to 30.2 A still gets the calibrator CMC (it is larger than
the coil DC rows there: tested on a grid); an ACI point from 20.5 A up to 120 A (and exactly 20.5 A) now also matches the coil rows (0.7 % + 0.84 A) and so takes that larger
CMC; no shipped procedure sources an AC current of 20.5 A or more (tested).
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'a2la_1888_03_cmc.json'
MARK = 'Coil lines added'


def _f(x):
    return float(x)


DC_BANDS = [dict(lo=2, hi=20, rel=_f(D('90') / D(10 ** 6)), abs=_f(D('0.1') * D('0.001')), rng=0.0),
            dict(lo=20, hi=120, rel=_f(D('80') / D(10 ** 6)), abs=_f(D('8') * D('0.001')), rng=0.0),
            dict(lo=120, hi=3000, rel=_f(D('0.8') / 100), abs=_f(D('0.08')), rng=0.0)]
AC_BLOCKS = [dict(lo=20.5, hi=1025.0, rows=[dict(f_lo=45.0, f_hi=65.0, rel=_f(D('0.8') / 100), abs=0.0, rng=0.0),
                                            dict(f_lo=65.0, f_hi=440.0, rel=_f(D('0.99') / 100), abs=0.0, rng=0.0)]),
             dict(lo=20.5, hi=3000.0, rows=[dict(f_lo=16.0, f_hi=850.0, rel=_f(D('0.7') / 100), abs=_f(D('0.84')), rng=0.0),
                                            dict(f_lo=850.0, f_hi=6000.0, rel=_f(D('0.8') / 100), abs=_f(D('0.84')), rng=0.0)])]
DC_NOTE = (' Coil lines added (p. 9 of 47, comment Transconductance amplifier/coil): (2 to 20) A 90 uA/A + 0.1 mA, (20 to 120) A 80 uA/A + 8 mA, (120 to 3000) A 0.8 % + 0.08 A.')
AC_NOTE = (' Coil lines added (p. 30 of 47): (20.5 to 3000) A (16 to 850) Hz 0.7 % + 0.84 A and (0.85 to 6) kHz 0.8 % + 0.84 A (Transconductance amplifier/coil); '
           'Clamp-On Only (20.5 to 1025) A (45 to 65) Hz 0.8 %, (65 to 440) Hz 0.99 % (Multifunction calibrator/coil).')


def apply(data):
    """Returns the data with the coil rows appended (a deep-enough copy is NOT made: pass freshly loaded data)."""
    dc = next(e for e in data['entries'] if e.get('basis') == 'generate' and e['kind'] == 'DCI')
    ac = next(e for e in data['entries'] if e.get('basis') == 'generate' and e['kind'] == 'ACI')
    if MARK in dc['notes'] or MARK in ac['notes']:
        return data                                                     # already applied
    dc['bands'].extend(dict(b) for b in DC_BANDS)
    ac['ranges'].extend(json.loads(json.dumps(b)) for b in AC_BLOCKS)
    dc['notes'] = (dc['notes'] + DC_NOTE).strip()
    ac['notes'] = (ac['notes'] + AC_NOTE).strip()
    dc['standard'] = dc['standard'] + ' / transconductance amplifier/coil'
    ac['standard'] = ac['standard'] + ' / coil (Clamp-On Only: multifunction calibrator/coil)'
    data['source'] = data['source'] + '; coil lines pp. 9 and 30'
    return data


def dumps(data):
    return json.dumps(data, indent=1, ensure_ascii=True)               # the file's own format (no trailing newline)


def main():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    before = len(data['entries'])
    apply(data)
    PATH.write_text(dumps(data), encoding='utf-8')
    print(f'{PATH.name}: {before} entries, coil rows present')


if __name__ == '__main__':
    main()
