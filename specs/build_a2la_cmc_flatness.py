"""Adds the A2LA scope's 'AC Voltage - Measure, AC Flatness - Relative to 1 kHz' lines to specs/a2la_1888_03_cmc.json (the lab CMC table read by
uncertainty.py), so the function-generator flatness points measured on the Fluke 5790B WIDEBAND input are 'in scope'.

    python specs/build_a2la_cmc_flatness.py          # idempotent (replaces its own ACFLAT entry); writes the file in its own format (json indent 1, ASCII escapes)

SOURCE: A2LA cert. 1888.03 rev. 07/07/2026, section V, printed pp. 22 to 28 of 47, 'AC Voltage - Measure (cont), AC Flatness - Relative to 1 kHz',
comment 'AC measurement standard', column CMC (+/-) in % (relative to the reading).  Transcribed by eye from the RENDERED PAGE IMAGES (pdftoppm -r 130,
2026-10-25), not from extracted text.

Each line is 'range / level' (the 5790B range and the level the line was established at) with SPOT frequencies grouped in rows; each row shares one CMC.
Owner's decision (2026-10-25): a row of spot frequencies is read as a BAND from its lowest to its highest listed frequency (5 MHz takes the
'3, 4, 6, 8, 9, 10 MHz' value); a frequency between two rows takes the LARGER of the two neighbouring rows; outside 10 Hz to 50 MHz nothing applies.
Level: the lines of the smallest range that holds the level apply, and the larger CMC of them is used (e.g. 0.335 V -> 0.7 V / 0.32 V and 0.7 V / 0.64 V).
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'a2la_1888_03_cmc.json'
k, M = 1e3, 1e6
LOW = ([10, 20], [50, 105, 200, 2 * k, 10 * k, 20 * k, 50 * k, 120 * k, 200 * k, 500 * k], [700 * k, 1 * M, 1.2 * M, 2 * M], [3 * M, 4 * M, 6 * M, 8 * M, 9 * M, 10 * M])

# (range V, level V, printed page, [(frequencies Hz, CMC %)])
LINES = [
    (2.2e-3, 1e-3, 22, [([10, 20], 0.12), ([50, 105, 200, 2 * k, 10 * k, 20 * k], 0.069), ([50 * k, 120 * k], 0.068),
                        ([200 * k, 500 * k, 700 * k, 1 * M, 1.2 * M, 2 * M], 0.18), (LOW[3], 0.28), ([12 * M, 15 * M, 17 * M, 20 * M], 0.41),
                        ([23 * M, 26 * M, 28 * M, 30 * M], 0.91), ([35 * M, 40 * M, 45 * M, 50 * M], 1.2)]),
    (7e-3, 3.2e-3, 22, [([10, 20], 0.11), ([50], 0.066), ([105], 0.069), ([200, 2 * k, 10 * k, 20 * k, 50 * k, 120 * k], 0.066),
                        ([200 * k, 500 * k, 700 * k, 1 * M, 1.2 * M, 2 * M], 0.11), (LOW[3], 0.14), ([12 * M, 15 * M, 17 * M], 0.21), ([20 * M], 0.22),
                        ([23 * M], 0.41), ([26 * M, 28 * M], 0.42), ([30 * M], 0.43), ([35 * M], 0.65), ([40 * M], 0.66), ([45 * M, 50 * M], 0.67)]),   # pp. 22-23
    (22e-3, 10e-3, 23, [([10, 20], 0.11), ([50, 105, 200, 2 * k, 10 * k, 20 * k, 50 * k, 120 * k], 0.066), ([200 * k, 500 * k], 0.082),
                        ([700 * k, 1 * M, 1.2 * M, 2 * M], 0.083), (LOW[3], 0.11), ([12 * M, 15 * M, 17 * M], 0.18), ([20 * M], 0.19), ([23 * M], 0.38),
                        ([26 * M, 28 * M], 0.39), ([30 * M], 0.40), ([35 * M], 0.62), ([40 * M, 45 * M], 0.63), ([50 * M], 0.64)]),
    (70e-3, 32e-3, 24, [([10, 20], 0.11), (LOW[1], 0.066), (LOW[2], 0.067), (LOW[3], 0.11), ([12 * M, 15 * M], 0.16), ([17 * M], 0.21), ([20 * M], 0.17),
                        ([23 * M], 0.36), ([26 * M, 28 * M], 0.37), ([30 * M], 0.38), ([35 * M], 0.62), ([40 * M, 45 * M], 0.63), ([50 * M], 0.64)]),
    (0.22, 0.1, 24, [([10, 20], 0.11), (LOW[1], 0.058), (LOW[2], 0.066), (LOW[3], 0.11), ([12 * M, 15 * M, 17 * M], 0.16), ([20 * M], 0.17),
                     ([23 * M], 0.36), ([26 * M, 28 * M], 0.37), ([30 * M], 0.38), ([35 * M, 40 * M], 0.62), ([45 * M, 50 * M], 0.63)]),          # pp. 24-25
    (0.7, 0.32, 25, [([10, 20], 0.11), (LOW[1], 0.052), (LOW[2], 0.066), (LOW[3], 0.11), ([12 * M, 15 * M, 17 * M], 0.16), ([20 * M], 0.17),
                     ([23 * M], 0.36), ([26 * M, 28 * M], 0.37), ([30 * M], 0.38), ([35 * M, 40 * M], 0.62), ([45 * M, 50 * M], 0.63)]),
]
_COMMON = [([10, 20], 0.11), (LOW[1], 0.052), (LOW[2], 0.066), (LOW[3], 0.11), ([12 * M, 15 * M, 17 * M], 0.16), ([20 * M], 0.17), ([23 * M], 0.36),
           ([26 * M, 28 * M, 30 * M], 0.37), ([35 * M, 40 * M], 0.62), ([45 * M, 50 * M], 0.63)]
LINES += [(0.7, 0.64, 26, _COMMON), (2.2, 1.0, 26, _COMMON), (2.2, 2.0, 27, _COMMON), (7.0, 3.2, 28, _COMMON)]       # pp. 26, 26-27, 27, 28: identical rows


def main():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    data['entries'] = [e for e in data['entries'] if e['kind'] != 'ACFLAT']
    lines = [dict(range=r, level=lv, page=pg, groups=[dict(freqs=[float(f) for f in fs], pct=pct) for fs, pct in groups]) for r, lv, pg, groups in LINES]
    data['entries'].append(dict(parameter='AC Voltage – Measure, AC Flatness – Relative to 1 kHz', kind='ACFLAT', standard='AC measurement standard',
                                notes=('Printed pp. 22-28 of 47, verified against the page images. CMC in % of the reading, relative to 1 kHz. Spot-frequency rows read as '
                                       'bands (lowest to highest listed frequency; between rows the larger neighbour); the smallest range holding the level, larger CMC '
                                       'of its lines (owner, 2026-10-25).'),
                                lines=lines, basis='measure'))
    PATH.write_text(json.dumps(data, indent=1, ensure_ascii=True), encoding='utf-8')
    print('written', len(lines), 'lines')


if __name__ == '__main__':
    main()
