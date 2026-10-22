"""Writes specs/keithley_2000_pv.json (Keithley Model 2000 6 1/2-digit multimeter, performance verification).

Source: Keithley Model 2000 Multimeter Calibration Manual (2000-905-01 Rev. F, Aug 2007), Section 1 "Performance Verification":
    Table 1-2  DCV reading limits          printed p. 1-7
    Table 1-3  ACV reading limits          printed p. 1-9   (note on the 219 V @ 50 kHz substitute)
    Table 1-4  DCI limits                  printed p. 1-10
    Table 1-5  ACI limits                  printed p. 1-11
    Table 1-6  Limits for resistance       printed p. 1-13  (procedure p. 1-12; 100 Mohm hook-up Figure 1-6)
Every limit below was read from the RENDERED PAGE IMAGES (pdftoppm), twice, not from extracted text (the extracted text corrupts the
Omega and micro signs). The manual states ONE interval only: "1 year, 18-28 C", calculated from the one-year accuracy specification
without test-equipment uncertainty (p. 1-5). That is the only period in the spec; the 90-day and 24-hour limits are not printed in the
verification section (they could be derived from the specification sheet, appendix A, but they are NOT in the verification tables).

CROSS-CHECK (this script fails if any printed limit disagrees): each printed half-width is recomputed in Decimal from the Model 2000
one-year accuracy specification (Calibration Manual appendix, "2000 6 1/2-Digit Multimeter Specifications", pp. 74-76 of the PDF):
    DC / ohms / DC current   +/-(ppm of reading + ppm of range)            1 year, 23 C +/-5 C
    1000 V DC                + 0.02 ppm/V for the portion above 500 V (DC note 9)
    AC volts                 +/-(% of reading + % of range)  10 Hz-20 kHz 0.06 + 0.03   20 kHz-50 kHz 0.12 + 0.05
    AC current               +/-(% of reading + % of range)  10 Hz-5 kHz   1 A 0.10 + 0.04   3 A 0.15 + 0.06
Where the printed limit is the rounded value of the exact figure (219 V @ 50 kHz: 0.6378 printed as 218.362 to 219.638 V) the PRINTED
half-width is used and the exact one is kept in 'computed_limit' for the record.

Each point carries a 'group' (the hook-up / diagram key), the 'range' the meter is set to (manual range selection, never autorange:
p. 1-6), and 'printed_limits' (the text as printed, for the record).  Run:  python specs/build_k2000_spec.py
"""
import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'keithley_2000_pv.json'
PERIOD = '1y'
DOC = 'Keithley Model 2000 Multimeter Calibration Manual (2000-905-01 Rev. F)'
SCALE = {'mV': D('0.001'), 'V': D(1), 'mA': D('0.001'), 'A': D(1), 'ohm': D(1), 'kohm': D(1000), 'Mohm': D(1000000)}


def printed(low, high, unit):
    """(low, high) in base units from the printed text (Decimal, exact)."""
    s = SCALE[unit]
    return D(low) * s, D(high) * s


def pt(kind, nominal, rng, low, high, unit, group, accuracy, frequency=None, **extra):
    """One point. `nominal` and the printed limits are decimal strings in `unit` (as in the manual's table); `accuracy` is the exact
    half-width in base units computed from the specification (Decimal). The printed half-width must equal it, or be its rounding."""
    s = SCALE[unit]
    nom = D(nominal) * s
    lo, hi = printed(low, high, unit)
    half_lo, half_hi = nom - lo, hi - nom
    if half_lo != half_hi:
        raise SystemExit(f'{kind} {nominal} {unit}: the printed limits are not symmetric about the nominal ({low} to {high})')
    exact = D(accuracy)
    if half_hi != exact:
        # the printed value may be the exact one rounded to the table's decimal places (only 219 V @ 50 kHz is)
        places = max(-D(low).as_tuple().exponent, -D(high).as_tuple().exponent)
        if abs(exact - half_hi) > s * D(10) ** (-places) / 2:          # more than half a unit of the last printed digit
            raise SystemExit(f'{kind} {nominal} {unit}: printed half-width {half_hi} disagrees with the specification ({exact})')
    p = dict(kind=kind, nominal=float(nom), range=extra.pop('range'), limits={PERIOD: float(half_hi)}, quick=False, group=group,
             printed_limits=f'{low} to {high} {unit}')
    if frequency:
        p['frequency'] = frequency
    if half_hi != exact:
        p['computed_limit'] = float(exact)
    p.update(extra)
    return p


def ppm(rdg_ppm, rng_ppm, reading, rng, extra_ppm=0):
    """+/-(ppm of reading + ppm of range [+ extra ppm of reading]) as an exact Decimal in base units."""
    return (D(reading) * (D(rdg_ppm) + D(extra_ppm)) + D(rng) * D(rng_ppm)) / D(1000000)


def pct(rdg, rng_pct, reading, rng):
    """+/-(% of reading + % of range) as an exact Decimal in base units."""
    return (D(reading) * D(rdg) + D(rng) * D(rng_pct)) / D(100)


# ---- Table 1-2: DC volts (p. 1-7). Positive AND negative full scale for every range. (ppm reading, ppm range) = 1 year ----------------------
DCV = [  # range V, applied (in the table's unit), unit, low, high, (ppm_r, ppm_g), extra ppm of reading
    ('0.1', '100.0000', 'mV', '99.9915', '100.0085', (50, 35), 0),
    ('1', '1.000000', 'V', '0.999963', '1.000037', (30, 7), 0),
    ('10', '10.00000', 'V', '9.99965', '10.00035', (30, 5), 0),
    ('100', '100.0000', 'V', '99.9949', '100.0051', (45, 6), 0),
    ('1000', '1000.000', 'V', '999.939', '1000.061', (45, 6), 10),      # + 0.02 ppm/V x (1000 - 500) V = 10 ppm of reading (DC note 9)
]
# ---- Table 1-3: AC volts (p. 1-9). 1 kHz = 10 Hz-20 kHz band, 50 kHz = 20 kHz-50 kHz band ----------------------------------------------------
ACV = [  # range V, applied, unit, (1 kHz low, high), (50 kHz low, high)
    ('0.1', '100.0000', 'mV', ('99.9100', '100.0900'), ('99.8300', '100.1700')),
    ('1', '1.000000', 'V', ('0.999100', '1.000900'), ('0.998300', '1.001700')),
    ('10', '10.00000', 'V', ('9.99100', '10.00900'), ('9.98300', '10.01700')),
    ('100', '100.0000', 'V', ('99.9100', '100.0900'), ('99.8300', '100.1700')),
]
ACV_1K, ACV_50K = (D('0.06'), D('0.03')), (D('0.12'), D('0.05'))
# ---- Table 1-4: DC current (p. 1-10), positive and negative ------------------------------------------------------------------------------------
DCI = [  # range A, applied, unit, low, high, (ppm_r, ppm_g)
    ('0.01', '10.0000', 'mA', '9.99420', '10.00580', (500, 80)),
    ('0.1', '100.0000', 'mA', '99.8700', '100.1300', (500, 800)),
    ('1', '1.000000', 'A', '0.999120', '1.000880', (800, 80)),
    ('3', '2.20000', 'A', '2.19724', '2.20276', (1200, 40)),
]
# ---- Table 1-6: resistance (p. 1-13) -------------------------------------------------------------------------------------------------------------
OHM = [  # range ohm, applied, unit, low, high, (ppm_r, ppm_g)
    ('100', '100', 'ohm', '99.9860', '100.0140', (100, 40)),
    ('1000', '1', 'kohm', '0.999890', '1.000110', (100, 10)),
    ('10000', '10', 'kohm', '9.99890', '10.00110', (100, 10)),
    ('100000', '100', 'kohm', '99.9890', '100.0110', (100, 10)),
    ('1000000', '1', 'Mohm', '0.999890', '1.000110', (100, 10)),
    ('10000000', '10', 'Mohm', '9.99590', '10.00410', (400, 10)),
]


def build():
    sections = []

    # ---- DC volts ----
    pts = []
    for rng, applied, unit, lo, hi, (pr, pg), extra in DCV:
        nom = D(applied) * SCALE[unit]
        exact = ppm(pr, pg, nom, rng, extra)
        pts.append(pt('DCV', applied, rng, lo, hi, unit, 'DCV', exact, range=float(rng), plc=1))
        neg_lo, neg_hi = '-' + hi, '-' + lo
        pts.append(pt('DCV', '-' + applied, rng, neg_lo, neg_hi, unit, 'DCV', exact, range=float(rng), plc=1))
    sections.append(dict(
        id='dcv', title='DC voltage', page='1-7 (Table 1-2)', group='DCV', source='calibrator', terminal='FRONT',
        setup='Connect the calibrator HI / LO to the 2000 INPUT HI / LO (Figure 1-1). Use shielded, low-thermal connections for the 100 mV and 1 V ranges, '
              'shield to the calibrator output LO. With the calibrator at 0.00000 mV DC the program enables REL on the 100 mV range and leaves it on '
              'for the remainder of the DC volts tests. Positive and negative values for each range.',
        points=pts))

    # ---- AC volts ----
    pts = []
    for rng, applied, unit, (lo1, hi1), (lo5, hi5) in ACV:
        nom = D(applied) * SCALE[unit]
        pts.append(pt('ACV', applied, rng, lo1, hi1, unit, 'ACV', pct(ACV_1K[0], ACV_1K[1], nom, rng), frequency=1000.0, range=float(rng)))
        pts.append(pt('ACV', applied, rng, lo5, hi5, unit, 'ACV', pct(ACV_50K[0], ACV_50K[1], nom, rng), frequency=50000.0, range=float(rng)))
    pts.append(pt('ACV', '700.000', '750', '699.355', '700.645', 'V', 'ACV', pct(ACV_1K[0], ACV_1K[1], 700, 750), frequency=1000.0, range=750.0))
    # the substitute step the manual allows when the 5725A amplifier is not available (p. 1-9 footnote): used unless the operator ticks the 700 V box
    pts.append(pt('ACV', '219', '750', '218.362', '219.638', 'V', 'ACV', pct(ACV_50K[0], ACV_50K[1], 219, 750), frequency=50000.0, range=750.0,
                  variant='alt219',
                  note='The manual substitutes 219 V at 50 kHz for the 700 V at 50 kHz step when the 5725A amplifier is not available (Table 1-3 footnote); '
                       'its limits are printed 218.362 to 219.638 V.'))
    sections.append(dict(
        id='acv', title='AC voltage', page='1-9 (Table 1-3)', group='ACV', source='calibrator', terminal='FRONT',
        setup='Connect the calibrator HI / LO to the 2000 INPUT HI / LO with shielded cable (Figure 1-2). ACV function, 100 mV range, REL disabled. '
              'Source 1 kHz and 50 kHz for each range.',
        points=pts))
    sections.append(dict(
        id='acv700', title='AC voltage 700 V at 50 kHz (5725A amplifier)', page='1-9 (Table 1-3)', group='ACV700', source='manual', optional=True,
        terminal='FRONT',
        setup='700.000 V at 50 kHz needs the Fluke 5725A amplifier with a 5700A-class calibrator (Figure 1-2): neither the 5522A nor the 5560A is '
              'assumed to make it. Source 700.000 V, 50 kHz by hand, in operate, let it settle, then confirm; the program reads the 2000 itself.',
        points=[pt('ACV', '700.000', '750', '698.785', '701.215', 'V', 'ACV700', pct(ACV_50K[0], ACV_50K[1], 700, 750), frequency=50000.0, range=750.0,
                   variant='opt700')]))

    # ---- DC current ----
    pts = []
    for rng, applied, unit, lo, hi, (pr, pg) in DCI:
        nom = D(applied) * SCALE[unit]
        exact = ppm(pr, pg, nom, rng)
        pts.append(pt('DCI', applied, rng, lo, hi, unit, 'DCI', exact, range=float(rng), plc=1))
        pts.append(pt('DCI', '-' + applied, rng, '-' + hi, '-' + lo, unit, 'DCI', exact, range=float(rng), plc=1))
    sections.append(dict(
        id='dci', title='DC current', page='1-10 (Table 1-4)', group='DCI', source='calibrator', terminal='FRONT',
        setup='Connect the calibrator current output (normal current output) to the 2000 AMPS and INPUT LO jacks (Figure 1-3). DCI function, 10 mA '
              'range first. Positive and negative values for each range. Check the AMPS fuse (3 A, 250 V) first.',
        points=pts))

    # ---- AC current ----
    sections.append(dict(
        id='aci', title='AC current', page='1-11 (Table 1-5)', group='ACI', source='calibrator', terminal='FRONT',
        setup='Connect the calibrator AC current output to the 2000 AMPS and INPUT LO jacks (Figure 1-4). ACI function, 1 A range first. 1 kHz.',
        points=[pt('ACI', '1.000000', '1', '0.998600', '1.001400', 'A', 'ACI', pct('0.10', '0.04', 1, 1), frequency=1000.0, range=1.0),
                pt('ACI', '2.20000', '3', '2.19490', '2.20510', 'A', 'ACI', pct('0.15', '0.06', D('2.2'), 3), frequency=1000.0, range=3.0)]))

    # ---- Resistance ----
    pts = []
    for rng, applied, unit, lo, hi, (pr, pg) in OHM:
        nom = D(applied) * SCALE[unit]
        pts.append(pt('OHM4', applied, rng, lo, hi, unit, 'OHM4', ppm(pr, pg, nom, rng), range=float(rng), plc=1))
    sections.append(dict(
        id='ohm4', title='Resistance 100 ohm to 10 Mohm (4-wire)', page='1-12 to 1-13 (Table 1-6)', group='OHM4', source='calibrator', terminal='FRONT',
        setup='Shielded 4-wire connections: 2000 INPUT and SENSE jacks to the calibrator (Figure 1-5), calibrator for 4-wire resistance with external sense ON. '
              'Select the 2000 4-wire resistance function (the manual says the Ohm4 key), 100 ohm range, FILTER on.',
        points=pts))
    sections.append(dict(
        id='ohm100m', title='Resistance 100 Mohm', page='1-12 to 1-13 (Table 1-6)', group='OHM100M', source='calibrator', terminal='FRONT',
        setup='Connect the 2000 INPUT and SENSE jacks to the calibrator as in Figure 1-6, with the calibrator external sense OFF (2-wire output); '
              'shielded cables. The manual selects the 100 Mohm range of the same Ohm4 function.',
        points=[pt('OHM4', '100', '100000000', '99.8470', '100.1530', 'Mohm', 'OHM100M', ppm(1500, 30, 100000000, 100000000), range=1e8, plc=1)]))

    return dict(
        schema=1, manufacturer='Keithley', model='2000', title='Model 2000 Performance Verification', idn_match=['MODEL 2000'],
        source=dict(document=DOC, pages='1-3 to 1-13 (Tables 1-2 to 1-6)',
                    note='One interval only: 1 year, 18-28 C (the manual calculates the limits from the one-year accuracy specification and does not include '
                         'calibrator uncertainty, p. 1-5; if a reading is slightly outside, the manual says to recalculate limits from the 2000 and the calibrator '
                         'specifications). The 90-day and 24-hour limits are not printed in the verification tables.'),
        periods=[PERIOD], default_period=PERIOD, front_rear_switch=True,
        equipment=dict(dc_ac_source='Fluke 5700A or equivalent (Table 1-1); this procedure drives a Fluke 5522A or 5560A',
                       high_voltage_ac='Fluke 5725A amplifier, only for 700 V at 50 kHz (otherwise 219 V at 50 kHz)', resistance='4-wire; 100 Mohm 2-wire'),
        general=['Warm up the 2000 for at least one hour before the verification (p. 1-3); allow the test equipment its own warm-up time.',
                 'Ambient 18 to 28 C, relative humidity below 80 % (p. 1-3); line 100 / 120 / 220 / 240 V +/-10 %, 45 to 66 Hz or 360 to 440 Hz.',
                 'Restore factory defaults first (Speed: medium, Filter: 10 readings, p. 1-5); front panel inputs selected with the INPUTS switch (p. 1-6).',
                 'Never use autorange: set the range for each test signal (p. 1-6). Calibrator in operate; always let the source signal settle before a reading.',
                 'Do not connect test equipment through a scanner or other switching equipment (p. 1-6).',
                 'Max common-mode voltage (INPUT LO to chassis) 500 V peak; do not exceed 1000 V peak between INPUT HI and LO, or 8 x 10^7 V-Hz (p. 1-8 caution).'],
        measure=dict(
            nplc=1, filter_state='ON', filter_count=10, filter_type='REPeat', ac_bandwidth=30,
            note='Speed medium = 1 PLC (DC, ohms, DC current) and detector bandwidth 30 (AC, "Medium" rate) with the digital filter on, 10 readings: the factory '
                 'default operating conditions the manual restores (p. 1-5, Table 2-2 of the User Manual). The filter is the REPEAT (one-shot) type so each '
                 ':READ? is ten fresh conversions; the specification sheet states MED (1 PLC) with a filter of 10 as its DC condition.'),
        prep=dict(dcv_rel_zero=dict(
            kind='DCV', range=0.1, nominal=0.0, page='1-7',
            text='Select DC volts, 100 mV range. Set the calibrator output to 0.00000 mV DC and allow the reading to settle, then enable the 2000 REL mode. '
                 'Leave REL enabled for the remainder of the DC volts verification tests (p. 1-7 steps 2 to 4). REL must be DISABLED for AC volts (p. 1-8 step 3).')),
        sections=sections)


def main():
    spec = build()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=True) + '\n', encoding='utf-8')
    total = sum(len(s['points']) for s in spec['sections'])
    print(f'wrote {OUT.name}: {total} points in {len(spec["sections"])} sections')


if __name__ == '__main__':
    main()
