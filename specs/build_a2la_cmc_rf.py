"""Writes specs/a2la_1888_03_rf.json: the A2LA scope's section VI 'Electrical - RF/Microwave' MEASURE lines (and the section V 'Distortion - Measure'
line), which specs/a2la_1888_03_cmc.json does not hold (that file is sections V and XII only, read by uncertainty.py and the Datasheet Builder).

    python specs/build_a2la_cmc_rf.py          # idempotent; writes the file in the suite's format (json indent 1, ASCII escapes)

A separate file on purpose: adding kinds to a2la_1888_03_cmc.json changes the Datasheet Builder's 'should have an uncertainty' set
(datasheet_builder_rules.CMC_KIND_MAP, a test fails on an unknown kind). Only fluke6060a_uncertainty.py reads this file.

SOURCE: A2LA cert. 1888.03 rev. 07/07/2026 (Applied Technical Services, valid to 2028-01-31), the owner's PDF '1888-03.pdf' (48 pages, sha256 afcf99394860c647...).
Transcribed by eye from the RENDERED PAGE IMAGES (pdftoppm -r 110, 2026-11-02) and compared with pdftotext -layout: they agree.
  printed p. 33 of 47: RF Power - Measure, RF Attenuation - Measure      (column 'CMC 2, 5, 9 (+/-)')
  printed p. 34 of 47: Amplitude / Frequency / Phase Modulation - Measure (column 'CMC 2, 5, 9 (+/-)')
  printed p. 28 of 47: Distortion - Measure (section V)                  (column 'CMC 2, 5, 9 (+/-)')
NOT transcribed: 'RF Power - Generate' and 'RF Level Linearity' (pp. 35-36, comment 'RF reference'): the 6060A procedures MEASURE the generator.
Footnote 9 (p. 47): 'This capability is suitable for the calibration of the devices intended to measure or generate the measured value in the ranges indicated.'

Reading rules (the same as the rest of the suite's scope tables, NOTES.md 'A2LA scope CMC tables'):
  - frequency bands printed '(lo to hi)' are closed; '>lo' (printed with '>') excludes its lower edge; on a shared edge the LARGER CMC is used;
  - the 'RF Power - Measure (-70 to -30) dBm' line prints its CMC in % with no basis: stored as printed (`pct`), its meaning is an OWNER DECISION
    (fluke6060a_uncertainty.RF_PCT_BASIS); the '(-30 to +20) dBm' line prints 'dBm' for a level difference: stored as dB.
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'a2la_1888_03_rf.json'
k, M, G = 1e3, 1e6, 1e9

DATA = {
    'schema': 1,
    'lab': 'Applied Technical Services, LLC.',
    'accreditor': 'A2LA',
    'certificate': '1888.03',
    'revised': '07/07/2026',
    'valid_to': '2028-01-31',
    'cmc_note': 'CMC = expanded uncertainty at approximately 95 % confidence (k = 2), footnote 2. It excludes the unit under test.',
    'source': 'Calibration Scope of Accreditation, section VI Electrical - RF/Microwave, printed pp. 33-34 of 47 (Measure lines); section V Distortion - Measure, p. 28',
    'entries': [
        {'parameter': 'RF Power - Measure', 'kind': 'RFPOWER', 'page': 33, 'bands': [
            # level lo/hi dBm, frequency lo/hi Hz (lo_open: printed '>'), CMC
            {'lv_lo': -70, 'lv_hi': -30, 'f_lo': 10 * M, 'f_hi': 30 * M, 'pct': 0.8, 'comment': 'Signal analyzer'},
            {'lv_lo': -70, 'lv_hi': -30, 'f_lo': 30 * M, 'f_hi': 4 * G, 'pct': 0.8, 'comment': 'Signal analyzer'},
            {'lv_lo': -70, 'lv_hi': -30, 'f_lo': 4 * G, 'f_hi': 6 * G, 'pct': 0.9, 'comment': 'Signal analyzer'},
            {'lv_lo': -70, 'lv_hi': -30, 'f_lo': 6 * G, 'f_hi': 10 * G, 'pct': 1.0, 'comment': 'Signal analyzer'},
            {'lv_lo': -70, 'lv_hi': -30, 'f_lo': 10 * G, 'f_hi': 12 * G, 'pct': 1.0, 'comment': 'Signal analyzer'},
            {'lv_lo': -70, 'lv_hi': -30, 'f_lo': 12 * G, 'f_hi': 14 * G, 'pct': 1.0, 'comment': 'Signal analyzer'},
            {'lv_lo': -70, 'lv_hi': -30, 'f_lo': 14 * G, 'f_hi': 15 * G, 'pct': 1.0, 'comment': 'Signal analyzer'},
            {'lv_lo': -70, 'lv_hi': -30, 'f_lo': 15 * G, 'f_hi': 18 * G, 'pct': 1.1, 'comment': 'Signal analyzer'},
            {'lv_lo': -30, 'lv_hi': 20, 'f_lo': 0.0, 'f_hi': 100 * M, 'db': 0.069, 'comment': 'RF measurement standard'},
            {'lv_lo': -30, 'lv_hi': 20, 'f_lo': 100 * M, 'f_hi': 2.4 * G, 'lo_open': True, 'db': 0.069, 'comment': 'RF measurement standard'},
            {'lv_lo': -30, 'lv_hi': 20, 'f_lo': 2.4 * G, 'f_hi': 8 * G, 'lo_open': True, 'db': 0.092, 'comment': 'RF measurement standard'},
            {'lv_lo': -30, 'lv_hi': 20, 'f_lo': 8 * G, 'f_hi': 12.4 * G, 'lo_open': True, 'db': 0.11, 'comment': 'RF measurement standard'},
            {'lv_lo': -30, 'lv_hi': 20, 'f_lo': 12.4 * G, 'f_hi': 18 * G, 'lo_open': True, 'db': 0.14, 'comment': 'RF measurement standard'},
            {'lv_lo': -30, 'lv_hi': 20, 'f_lo': 18 * G, 'f_hi': 26.5 * G, 'lo_open': True, 'db': 0.15, 'comment': 'RF measurement standard'},
        ]},
        {'parameter': 'RF Attenuation - Measure', 'kind': 'RFATTEN', 'page': 33, 'f_lo': 10 * M, 'f_hi': 1.3 * G, 'comment': 'RF measurement standard', 'bands': [
            {'db_lo': lo, 'db_hi': lo + 10, 'db': cmc} for lo, cmc in
            ((0, 0.064), (10, 0.067), (20, 0.069), (30, 0.082), (40, 0.10), (50, 0.10), (60, 0.11), (70, 0.11), (80, 0.14), (90, 0.14), (100, 0.15), (110, 0.22))]},
        {'parameter': 'Amplitude Modulation - Measure', 'kind': 'AM', 'page': 34, 'comment': 'RF measurement standard', 'bands': [
            # rate lo/hi Hz, carrier lo/hi Hz, depth % lo/hi, CMC % of reading
            {'rate_lo': 50, 'rate_hi': 10 * k, 'f_lo': 0.15 * M, 'f_hi': 10 * M, 'depth_lo': 5, 'depth_hi': 99, 'pct': 2.4},
            {'rate_lo': 20, 'rate_hi': 10 * k, 'f_lo': 0.15 * M, 'f_hi': 10 * M, 'depth_lo': 5, 'depth_hi': 99, 'pct': 3.5},
            {'rate_lo': 20, 'rate_hi': 100 * k, 'f_lo': 1.3 * G, 'f_hi': 1.6 * G, 'depth_lo': 5, 'depth_hi': 99, 'pct': 3.5},
            {'rate_lo': 50, 'rate_hi': 50 * k, 'f_lo': 1.3 * G, 'f_hi': 26.5 * G, 'depth_lo': 5, 'depth_hi': 99, 'pct': 3.5},
            {'rate_lo': 20, 'rate_hi': 100 * k, 'f_lo': 1.3 * G, 'f_hi': 26.5 * G, 'depth_lo': 5, 'depth_hi': 99, 'pct': 3.5},
        ]},
        {'parameter': 'Frequency Modulation - Measure', 'kind': 'FM', 'page': 34, 'comment': 'RF measurement standard', 'bands': [
            # rate lo/hi Hz, carrier lo/hi Hz, peak deviation limit Hz, CMC % of reading
            {'rate_lo': 20, 'rate_hi': 10 * k, 'f_lo': 0.15 * M, 'f_hi': 10 * M, 'dev_max': 40 * k, 'pct': 2.6},
            {'rate_lo': 50, 'rate_hi': 100 * k, 'f_lo': 0.02 * G, 'f_hi': 1.3 * G, 'dev_max': 400 * k, 'pct': 1.3},
            {'rate_lo': 20, 'rate_hi': 200 * k, 'f_lo': 0.02 * G, 'f_hi': 1.3 * G, 'dev_max': 4 * k, 'pct': 5.9},
            {'rate_lo': 50, 'rate_hi': 100 * k, 'f_lo': 1.3 * G, 'f_hi': 26.5 * G, 'dev_max': 400 * k, 'pct': 3.7},
            {'rate_lo': 20, 'rate_hi': 200 * k, 'f_lo': 1.3 * G, 'f_hi': 26.5 * G, 'dev_max': 400 * k, 'pct': 3.7},
        ]},
        {'parameter': 'Phase Modulation - Measure', 'kind': 'PM', 'page': 34, 'comment': 'RF measurement standard', 'bands': [
            {'rate_lo': 100, 'rate_hi': 20 * k, 'f_lo': 150 * k, 'f_hi': 1.3 * G, 'pct': 3.7},
            {'rate_lo': 100, 'rate_hi': 20 * k, 'f_lo': 1.3 * G, 'f_hi': 26.5 * G, 'pct': 3.7},
        ]},
        {'parameter': 'Distortion - Measure', 'kind': 'DIST', 'page': 28, 'section': 'V', 'comment': 'Distortion analyzer', 'bands': [
            # distortion level dB (0 = 100 %), fundamental frequency Hz, CMC dB
            {'db_lo': -80, 'db_hi': 0, 'f_lo': 20, 'f_hi': 20 * k, 'db': 1.2},
            {'db_lo': -70, 'db_hi': 0, 'f_lo': 20 * k, 'f_hi': 50 * k, 'db': 2.3},
            {'db_lo': -65, 'db_hi': 0, 'f_lo': 50 * k, 'f_hi': 100 * k, 'db': 2.3},
        ]},
    ],
}


def main():
    PATH.write_text(json.dumps(DATA, indent=1) + '\n', encoding='utf-8')
    print(f'wrote {PATH} ({sum(len(e["bands"]) for e in DATA["entries"])} lines)')


if __name__ == '__main__':
    main()
