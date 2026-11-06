"""Writes specs/a2la_1888_03_time.json: the A2LA scope's 'Time Marker' line (Section XII Time & Frequency), which specs/a2la_1888_03_cmc.json does not hold.

    python specs/build_a2la_cmc_time.py          # idempotent; writes the file in the suite's format (json indent 1, ASCII escapes)

A separate file on purpose, as specs/a2la_1888_03_rf.json: adding a kind to a2la_1888_03_cmc.json changes the Datasheet Builder's 'should have an uncertainty' set.
Only keysight_53220a_verification.py reads this file (Test 5 time interval, owner decision 2026-11-06).

SOURCE: the owner's screenshot of the scope line, 2026-11-06 ("use this for time interval"), transcribed by eye:
    Time Marker    1 ns to 20 ms     3 us/s
                   50 ms to 5 s      (30 + 1000t) us/s        t = time in seconds
The page number of the line in the certificate (1888.03) is not known here: UNVERIFIED against the full scope document.
Reading: the CMC is relative to the time t: CMC(t) = (a + b t) x 1e-6 x t seconds, with a = 3, b = 0 from 1 ns to 20 ms and a = 30, b = 1000 from 50 ms to 5 s.
The bands are closed as printed; 20 ms to 50 ms is NOT covered (no line), so nothing is assumed there.
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'a2la_1888_03_time.json'

DATA = {
    'schema': 1,
    'lab': 'Applied Technical Services',
    'accreditor': 'A2LA',
    'certificate': '1888.03',
    'source': "Owner's screenshot of the scope's 'Time Marker' line, 2026-11-06 (page number not recorded: UNVERIFIED against the full scope)",
    'entries': [
        {'parameter': 'Time Marker', 'kind': 'TIME', 'unit': 's',
         'cmc_note': 'CMC = (a + b * t) us/s of the time t (t in seconds)',
         'bands': [{'lo': 1e-9, 'hi': 20e-3, 'a_us_per_s': 3.0, 'b_us_per_s2': 0.0, 'printed': '3 us/s'},
                   {'lo': 50e-3, 'hi': 5.0, 'a_us_per_s': 30.0, 'b_us_per_s2': 1000.0, 'printed': '(30 + 1000t) us/s'}]},
    ],
}


def time_marker_cmc(t, data=None):
    """The scope's Time Marker CMC in seconds for a time t (seconds), or None outside the printed bands."""
    for e in (data or DATA)['entries']:
        if e['kind'] != 'TIME':
            continue
        for b in e['bands']:
            if b['lo'] <= t <= b['hi']:
                return (b['a_us_per_s'] + b['b_us_per_s2'] * t) * 1e-6 * t
    return None


def main():
    PATH.write_text(json.dumps(DATA, indent=1, ensure_ascii=True) + '\n', encoding='utf-8')
    print(f'wrote {PATH}')


if __name__ == '__main__':
    main()
