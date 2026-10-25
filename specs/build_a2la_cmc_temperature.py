"""Adds the A2LA scope's thermocouple lines (types B C D E J K L N R S T U) to specs/a2la_1888_03_cmc.json (the lab CMC table read by uncertainty.py), so the temperature
points of the handheld procedures (thermocouple simulation, Type K) are 'in scope' and carry the CMC as a floor like every other kind.

    python specs/build_a2la_cmc_temperature.py          # idempotent (replaces its own TEMP entry); rewrites the file in its own format (json indent 1, ASCII escapes, no final newline)

SOURCE: A2LA cert. 1888.03 rev. 07/07/2026, section V, printed pp. 12 (B C D) and 13 (E J K L N R S T U) of 47, 'Electrical Calibration of Thermocouple Indicators (cont)', comment 'Multifunction calibrator',
column CMC (+/-), degC.  VERIFIED against the rendered page image (supplied 2026-10-24).  Type K also agrees with the 5560A Type K 1-year 95 % specification
(0.22 0.10 0.09 0.16 0.27: every CMC is >= the calibrator specification).  Types BP, XK (p. 14) are not added: no procedure uses them yet.
Bands printed '(> lo to hi)' are lower-exclusive (gt=True): an edge belongs to the lower band.  Type N prints its bands WITHOUT '>' (closed intervals): on an edge the larger
CMC is used, as everywhere else in the table.
The entry's 'bands' are Type K (what the handheld procedures simulate); 'types' holds every type.
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'a2la_1888_03_cmc.json'
# type: [(lo, hi, cmc, printed with '>')]
TYPES = {
    'B': [(600, 800, 0.34, 0), (800, 1000, 0.26, 1), (1000, 1550, 0.23, 1), (1550, 1820, 0.26, 1)],                    # printed p. 12 of 47
    'C': [(0, 150, 0.19, 0), (150, 650, 0.16, 1), (650, 1000, 0.20, 1), (1000, 1800, 0.35, 1), (1800, 2316, 0.61, 1)],  # printed p. 12 of 47
    'D': [(0, 150, 0.19, 0), (150, 650, 0.16, 1), (650, 1000, 0.20, 1), (1000, 1800, 0.34, 1), (1800, 2316, 0.61, 1)],  # printed p. 12 of 47
    'E': [(-250, -150, 0.31, 0), (-150, -25, 0.12, 1), (-25, 350, 0.10, 1), (350, 650, 0.13, 1), (650, 1000, 0.16, 1)],
    'J': [(-210, -100, 0.19, 0), (-100, -30, 0.11, 1), (-30, 150, 0.10, 1), (150, 760, 0.12, 1), (760, 1200, 0.16, 1)],
    'K': [(-200, -100, 0.22, 0), (-100, -25, 0.11, 1), (-25, 120, 0.10, 1), (120, 1000, 0.16, 1), (1000, 1372, 0.27, 1)],
    'L': [(-200, -100, 0.24, 0), (-100, 800, 0.16, 1), (800, 900, 0.10, 1)],
    'N': [(-200, -100, 0.26, 0), (-100, -25, 0.13, 0), (-25, 120, 0.10, 0), (120, 410, 0.10, 0), (410, 1300, 0.16, 0)],
    'R': [(0, 250, 0.40, 0), (250, 400, 0.23, 1), (400, 1000, 0.21, 1), (1000, 1767, 0.26, 1)],
    'S': [(0, 250, 0.33, 0), (250, 1000, 0.24, 1), (1000, 1400, 0.25, 1), (1400, 1767, 0.32, 1)],
    'T': [(-250, -150, 0.47, 0), (-150, 0, 0.16, 1), (0, 120, 0.11, 1), (120, 400, 0.10, 1)],
    'U': [(-200, 0, 0.31, 0), (0, 600, 0.10, 1)],
}


def bands(rows):
    return [dict(lo=lo, hi=hi, rel=0.0, abs=v, rng=0.0, gt=bool(gt)) for lo, hi, v, gt in rows]


def main():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    data['entries'] = [e for e in data['entries'] if e['kind'] != 'TEMP']
    data['entries'].append(dict(parameter='Electrical Calibration of Thermocouple Indicators', kind='TEMP', standard='Multifunction calibrator',
                                notes='Thermocouple simulation, degC (printed p. 13 of 47, verified against the page image). bands = Type K; types = B C D E J K L N R S T U.',
                                bands=bands(TYPES['K']), types={t: bands(r) for t, r in TYPES.items()}, basis='generate'))
    PATH.write_text(json.dumps(data, indent=1, ensure_ascii=True), encoding='utf-8')
    print('written')


if __name__ == '__main__':
    main()
