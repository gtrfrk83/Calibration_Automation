"""Adds the A2LA scope's 'AC Power - Generate' line to specs/a2la_1888_03_cmc.json (the lab CMC table read by uncertainty.py), so AC power points get a scope CMC.

    python specs/build_a2la_cmc_power.py            # idempotent: adds the entry once, rewrites the file in the file's own format (json indent 1, ASCII escapes, no final newline)

This script ONLY appends one entry; every existing entry is kept as it is (tests/test_a2la_cmc_power.py).  SOURCE: the owner's screenshot of the scope
(A2LA cert. 1888.03 rev. 07/07/2026), 2026-11-05, comment 'Multifunction calibrator', conditions '(45 to 65) Hz; PF = 1':
    (0.01 to 0.1) W 0.23 %;  (0.1 to 890) W 0.13 %;  (0.89 to 3) kW 0.13 %;  (3 to 20.5) kW 0.13 %;  (20.5 to 120) kW 0.10 %
UNVERIFIED: the printed page number and the text of the heading's footnote 3 (neither was in the screenshot).  The CMC holds only at PF = 1 (the lookup has no
power-factor input, so the condition is kept in the notes; a caller must not use it for another power factor).
Lookup (uncertainty.Scope.dmm, kind 'POWAC', basis 'generate'): bands by the generated power in W and the frequency; closed intervals, an overlap edge takes the
larger CMC (exactly 0.1 W -> 0.23 %).
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'a2la_1888_03_cmc.json'
PARAMETER = 'AC Power – Generate'
LINES = (('0.01', '0.1', '0.23'), ('0.1', '890', '0.13'), ('890', '3000', '0.13'), ('3000', '20500', '0.13'), ('20500', '120000', '0.10'))
NOTES = ('Bands by the generated power (W) at (45 to 65) Hz and PF = 1 only (footnote 3 of the scope heading: text not transcribed, UNVERIFIED). '
         'Added 2026-11-05 from the owner\'s screenshot of the scope; page number not recorded.')


def entry():
    return dict(parameter=PARAMETER, kind='POWAC', standard='Multifunction calibrator', notes=NOTES,
                ranges=[dict(lo=float(D(lo)), hi=float(D(hi)), rows=[dict(f_lo=45.0, f_hi=65.0, rel=float(D(pct) / 100), abs=0.0, rng=0.0)])
                        for lo, hi, pct in LINES],
                basis='generate', pf=1.0)


def apply(data):
    """Returns the data with the AC power entry appended (once)."""
    if not any(e['parameter'] == PARAMETER for e in data['entries']):
        data['entries'].append(entry())
    return data


def dumps(data):
    return json.dumps(data, indent=1, ensure_ascii=True)               # the file's own format (no trailing newline)


def main():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    apply(data)
    PATH.write_text(dumps(data), encoding='utf-8')
    print(f'{PATH.name}: {len(data["entries"])} entries, AC power line present')


if __name__ == '__main__':
    main()
