"""Writes specs/keysight_33210a_pv.json, keysight_33220a_pv.json and keysight_33250a_pv.json (schema 4: function generators).

Every value below was read from the rendered page images of the Calibration Procedures chapter (Chapter 4) of each Service Guide,
not from extracted text. Printed page numbers:

                                33210A Service Guide   33220A Service Guide   33250A Service Guide
  Recommended Test Equipment           62                     58                     53
  Test Considerations                  63                     59                     54
  Self-Test                            64                     60                     56
  Amplitude/Flatness Worksheet         67                     63                     59
  Internal Timebase Verification       68                     64                     60
  AC Amplitude (high-impedance)        69                     65                     61
  Low Frequency Flatness               71                     66                     62
  0 dB Range Flatness                  72-73                  67-68                  63-64
  +10 dB Range Flatness                74-75                  69-70                  65
  +20 dB Range Flatness                76-77                  71-72                  66-67

Printed-table quirks, applied as noted:
  * 33210A p. 69 prints the 670 mVrms frequency as "1.0v00 kHz": applied as 1.000 kHz.
  * 33210A p. 71 and 33220A p. 66 footnote the 2.000 Vrms row as "1k00Hz_10dB_reference": it is the 100 kHz +10 dB reference.
  * 33250A p. 62 prints the 2 V amplitude as "2.0 Vrms": applied as 2.000 Vrms (nominal printed 2.000 Vrms).
  * 33250A p. 61 footnote 4: square-wave amplitude accuracy is not specified; the row is a guideline (marked typical).
  * 33250A pp. 63-67 do not repeat the "Relative Power" step the other two manuals give; the same method is used for all three.
  * Timebase limit: 33210A / 33220A +/-100 Hz within 90 days of calibration, +/-200 Hz within one year (footnote); 33250A +/-20 Hz.

Run:  python specs/build_fgen_spec.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

AC_AMPLITUDE = [   # (function, Vrms setting = nominal, error Vrms, worksheet reference)   identical in all three manuals
    ('SIN', 0.020, 0.00091, None), ('SIN', 0.067, 0.00138, None), ('SIN', 0.200, 0.00271, None),
    ('SIN', 0.670, 0.00741, '1k_0dB'), ('SIN', 2.000, 0.0207, '1k_10dB'), ('SIN', 7.000, 0.0707, '1k_20dB'),
    ('SQU', 0.900, 0.0100, None),
]
LF_FLATNESS = [(0.670, 0.0067, '100k_0dB'), (2.000, 0.020, '100k_10dB'), (7.000, 0.070, '100k_20dB')]
RANGES = [(0, 3.51), (10, 13.00), (20, 23.90)]      # attenuator range (dB) and the dBm setting the manual uses

MODELS = {
    '33210A': dict(
        brand='Keysight', doc='Keysight 33210A 10 MHz Function / Arbitrary Waveform Generator Service Guide',
        pages=dict(equipment=62, considerations=63, selftest=64, worksheet=67, timebase=68, acamp=69, lf=71,
                   flat0='72-73', flat10='74-75', flat20='76-77'),
        temperature='21 to 25 C (23 C +/-2 C), humidity below 80 %, 1 hour warm-up',
        timebase={'90d': 100.0, '1y': 200.0},
        # (frequency Hz, error dB, quick)  - the same table is printed for the 0, +10 and +20 dB ranges
        flatness=[(100e3, 0.1, True), (200e3, 0.2, False), (500e3, 0.2, False), (2e6, 0.2, False), (3e6, 0.2, False),
                  (4e6, 0.2, True), (5e6, 0.2, False), (8e6, 0.3, False), (10e6, 0.3, True)],
        square_typical=False),
    '33220A': dict(
        brand='Agilent', doc='Agilent 33220A 20 MHz Function / Arbitrary Waveform Generator Service Guide',
        pages=dict(equipment=58, considerations=59, selftest=60, worksheet=63, timebase=64, acamp=65, lf=66,
                   flat0='67-68', flat10='69-70', flat20='71-72'),
        temperature='21 to 25 C (23 C +/-2 C), humidity below 80 %, 1 hour warm-up',
        timebase={'90d': 100.0, '1y': 200.0},
        flatness=[(100e3, 0.1, True), (200e3, 0.15, False), (500e3, 0.15, False), (2e6, 0.15, False), (3e6, 0.15, False),
                  (4e6, 0.15, True), (5e6, 0.15, False), (8e6, 0.3, False), (10e6, 0.3, True), (12.5e6, 0.3, False),
                  (14e6, 0.3, False), (16e6, 0.3, False), (17.5e6, 0.3, False), (20e6, 0.3, True)],
        square_typical=False),
    '33250A': dict(
        brand='Agilent', doc='Agilent 33250A 80 MHz Function / Arbitrary Waveform Generator Service Guide',
        pages=dict(equipment=53, considerations=54, selftest=56, worksheet=59, timebase=60, acamp=61, lf=62,
                   flat0='63-64', flat10='65', flat20='66-67'),
        temperature='18 to 28 C (ideally 23 C +/-1 C), humidity below 80 %, 1 hour warm-up',
        timebase={'90d': 20.0, '1y': 20.0},
        flatness=[(100e3, 0.086, True), (200e3, 0.086, False), (500e3, 0.086, False), (1.5e6, 0.086, False), (5e6, 0.086, False),
                  (10e6, 0.086, True), (25e6, 0.177, False), (40e6, 0.177, False), (50e6, 0.177, True), (60e6, 0.423, False),
                  (65e6, 0.423, False), (70e6, 0.423, False), (75e6, 0.423, False), (80e6, 0.423, True)],
        square_typical=True),
}

PERIODS = ['90d', '1y']


def both(value):
    return {p: value for p in PERIODS}


def build(model):
    m = MODELS[model]
    pg = m['pages']
    sections = [
        dict(id='selftest', title='Self-Test', page=pg['selftest'], kind='SELFTEST', group='NONE',
             setup='No connections are needed. The generator runs its complete self-test (*TST?).',
             points=[dict(kind='SELFTEST', nominal=0, unit='', limits=both(0.5), quick=True)]),
        dict(id='timebase', title='Internal Timebase', page=pg['timebase'], kind='TIMEBASE', group='COUNTER',
             setup='Generator OUTPUT to the frequency counter input; counter input terminated at 50 ohm.',
             points=[dict(kind='TIMEBASE', function='SIN', frequency=10e6, amplitude=1.00, amp_unit='VPP', load='50',
                          nominal=10e6, unit='Hz', limits=dict(m['timebase']), quick=True)]),
        dict(id='acamp', title='AC Amplitude (High-Z)', page=pg['acamp'], kind='ACAMP', group='STD',
             setup='Generator OUTPUT to the 5790B INPUT 1 (type N) with a BNC cable and an N(m)-BNC(f) adapter. Output setup High Z.',
             points=[]),
        dict(id='lfflat', title='Low Frequency Flatness', page=pg['lf'], kind='LFFLAT', group='STD',
             setup='Same connection as AC Amplitude. 100 kHz, output setup High Z.', points=[]),
    ]
    for func, v, err, ref in AC_AMPLITUDE:
        p = dict(kind='ACAMP', function=func, frequency=1e3, amplitude=v, amp_unit='VRMS', load='INF',
                 nominal=v, unit='V', limits=both(err), quick=True)
        if ref: p['ref'] = ref
        if func == 'SQU' and m['square_typical']:
            p['typical'] = True
            p['note'] = 'Square-wave amplitude accuracy is not specified; the manual gives this limit as a guideline for typical operation.'
        sections[2]['points'].append(p)
    for v, err, ref in LF_FLATNESS:
        sections[3]['points'].append(dict(kind='LFFLAT', function='SIN', frequency=100e3, amplitude=v, amp_unit='VRMS', load='INF',
                                          nominal=v, unit='V', limits=both(err), quick=True, ref=ref))
    for rng, dbm in RANGES:
        key = {0: 'flat0', 10: 'flat10', 20: 'flat20'}[rng]
        title = {0: '0 dB Range Flatness', 10: '+10 dB Range Flatness', 20: '+20 dB Range Flatness'}[rng]
        group = 'POWER_ATT' if rng == 20 else 'POWER'
        setup = ('Generator OUTPUT to the power sensor' + (' through the -20 dB attenuator' if rng == 20 else '') +
                 '. Output setup 50 ohm. Flatness is relative to 1 kHz: the 100 kHz reading is the reference and the worksheet '
                 f'offset 100kHz_{rng}dB_offset is added (manual: power meter Relative Power + offset).')
        pts = [dict(kind='FLAT', function='SIN', frequency=f, amplitude=dbm, amp_unit='DBM', load='50', range_db=rng,
                    nominal=0.0, unit='dB', limits=both(e), quick=q) for f, e, q in m['flatness']]
        sections.append(dict(id=key, title=title, page=pg[key], kind='FLAT', group=group, range_db=rng, setup=setup, points=pts))
    return {
        'schema': 4,
        'manufacturer': m['brand'],
        'model': model,
        'title': f'{m["brand"]} {model} Performance Verification',
        'source': dict(document=m['doc'], chapter='Chapter 4 Calibration Procedures',
                       pages=f'{pg["equipment"]}-{pg["flat20"].split("-")[-1]}',
                       worksheet_page=pg['worksheet'], considerations_page=pg['considerations'],
                       conditions=m['temperature'],
                       note=('Limits are the manufacturer verification limits as printed (Q = quick verification). The manual notes that if no '
                             'adjustment is made the limits must be guard-banded to no more than 80 % of the Chapter 1 specifications; '
                             'that guard band is not applied here. Equipment: the manual lists a Keysight 3458A DMM for the AC amplitude '
                             'and low-frequency flatness tests; this procedure uses a Fluke 5790B. Power meter E4418B with 8482A sensor and '
                             '8491A Opt 020 attenuator; frequency counter 53131A Opt 010.')),
        'periods': PERIODS,
        'default_period': '1y',
        'references': {
            'offset_0dB': ['100k_0dB', '1k_0dB'], 'offset_10dB': ['100k_10dB', '1k_10dB'], 'offset_20dB': ['100k_20dB', '1k_20dB'],
            'formula': 'offset_N = 10 log(5 Vrms(100 kHz)^2) - 10 log(5 Vrms(1 kHz)^2)  (worksheet; Vrms High-Z to dBm at 50 ohm)'},
        'sections': sections,
    }


def main():
    for model in MODELS:
        spec = build(model)
        path = HERE / f'keysight_{model.lower()}_pv.json'
        path.write_text(json.dumps(spec, indent=1) + '\n', encoding='utf-8')
        n = sum(len(s['points']) for s in spec['sections'])
        print(f'{path.name}: {n} points')


if __name__ == '__main__':
    main()
