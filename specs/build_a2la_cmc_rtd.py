"""Adds the A2LA scope's 'Electrical Calibration of RTDs' lines to the TEMP entry of specs/a2la_1888_03_cmc.json (the lab CMC table read by uncertainty.py),
beside the thermocouple types, so RTD simulation points are 'in scope' and carry the CMC as a floor like the thermocouple points.

    python specs/build_a2la_cmc_rtd.py          # idempotent (replaces its own RTD keys in TEMP['types']); rewrites the file in its own format (json indent 1, ASCII escapes, no final newline)

SOURCE: A2LA cert. 1888.03 rev. 07/07/2026, section V, printed pp. 14 (Pt 385 100, Pt 3926 100, Pt 3916 100, Pt 385 200) and 15 (Pt 385 500, Pt 385 1000, Ni 672 120,
Cu 427 10) of 47, 'Electrical Calibration of RTDs', comment 'Multifunction calibrator', column CMC (+/-), degC.  Transcribed by eye from the RENDERED PAGE IMAGES
(pdftoppm -r 130 and a 220 dpi crop of each table, 2026-10-25), every number read twice, not from extracted text.  Bands are shaped exactly as the thermocouple
types: {'lo','hi','rel','abs','rng','gt'}; a band printed '(> lo to hi)' is lower-exclusive (gt=True: an edge belongs to the band below), the lowest band of a type
('lo to hi') is closed.  The printed Pt 385, 100 ohm first line reads '(-200 0) degC' (the 'to' is missing in the certificate): read as (-200 to 0).

CANONICAL KEYS (shared with the Datasheet Builder's temperature 'sourced as' choice; do not rename):
    Pt385-100  Pt385-200  Pt385-500  Pt385-1000  Pt3926-100  Pt3916-100  Pt395-100  Cu427-10  PtNi385-120
'Pt395-100' is NOT printed on the scope, so it has no bands (a lookup returns None).  The scope's nickel line is 'Ni 672, 120 ohm', filed under the canonical key 'PtNi385-120'.
Order matters only for display (uncertainty.sensor_types): thermocouples first, then the RTDs in the order of RTD_ORDER.
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'a2la_1888_03_cmc.json'

# key: (printed page, [(lo, hi, CMC degC, printed with '>')])
RTDS = {
    'Pt385-100': (14, [(-200, 0, 0.041, 0), (0, 100, 0.052, 1), (100, 300, 0.073, 1), (300, 400, 0.083, 1), (400, 630, 0.095, 1), (630, 800, 0.18, 1)]),
    'Pt385-200': (14, [(-200, 0, 0.031, 0), (0, 100, 0.032, 1), (100, 260, 0.043, 1), (260, 300, 0.092, 1), (300, 400, 0.10, 1), (400, 600, 0.11, 1), (600, 630, 0.12, 1)]),
    'Pt385-500': (15, [(-200, 0, 0.031, 0), (0, 100, 0.032, 1), (100, 260, 0.042, 1), (260, 300, 0.091, 1), (300, 400, 0.10, 1), (400, 600, 0.12, 1), (600, 630, 0.13, 1)]),
    'Pt385-1000': (15, [(-200, 0, 0.021, 0), (0, 100, 0.033, 1), (100, 260, 0.044, 1), (260, 300, 0.054, 1), (300, 400, 0.055, 1), (400, 600, 0.058, 1), (600, 630, 0.18, 1)]),
    'Pt3926-100': (14, [(-200, 0, 0.041, 0), (0, 100, 0.052, 1), (100, 300, 0.073, 1), (300, 400, 0.083, 1), (400, 630, 0.095, 1)]),
    'Pt3916-100': (14, [(-200, 0, 0.041, 0), (0, 100, 0.052, 1), (100, 300, 0.073, 1), (300, 400, 0.083, 1), (400, 630, 0.095, 1)]),
    'Cu427-10': (15, [(-80, 260, 0.25, 0)]),
    'PtNi385-120': (15, [(-80, 0, 0.021, 0), (0, 100, 0.031, 1), (100, 260, 0.042, 1)]),          # printed 'Ni 672, 120 ohm'
}
RTD_ORDER = ('Pt385-100', 'Pt385-200', 'Pt385-500', 'Pt385-1000', 'Pt3926-100', 'Pt3916-100', 'Pt395-100', 'Cu427-10', 'PtNi385-120')
NOTES = ('Thermocouple and RTD simulation, degC. Thermocouples: printed pp. 12-13 of 47 (types B C D p. 12, E J K L N R S T U p. 13), bands = Type K; types = B C D E J K L N R S T U '
         '(Types BP and XK, p. 14, are not loaded). RTDs: printed pp. 14-15 of 47, types Pt385-100 Pt385-200 Pt385-500 Pt385-1000 Pt3926-100 Pt3916-100 Cu427-10 PtNi385-120 '
         '(scope line "Ni 672, 120 ohm"); Pt395-100 is not on the scope. All verified against the rendered page images.')


def bands(rows):
    return [dict(lo=lo, hi=hi, rel=0.0, abs=v, rng=0.0, gt=bool(gt)) for lo, hi, v, gt in rows]


def apply(data):
    """Adds (or replaces) the RTD keys in the TEMP entry's types and refreshes its notes; returns data."""
    entry = next(e for e in data['entries'] if e['kind'] == 'TEMP')
    for key in RTD_ORDER:
        entry['types'].pop(key, None)
    for key in RTD_ORDER:
        if key in RTDS:
            entry['types'][key] = bands(RTDS[key][1])
    entry['notes'] = NOTES
    return data


def dumps(data):
    return json.dumps(data, indent=1, ensure_ascii=True)


def main():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    PATH.write_text(dumps(apply(data)), encoding='utf-8')
    print('written', len(RTDS), 'RTD types')


if __name__ == '__main__':
    main()
