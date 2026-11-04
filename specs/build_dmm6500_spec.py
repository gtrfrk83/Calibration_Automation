"""Writes specs/keithley_dmm6500_pv.json (Keithley DMM6500 6 1/2-digit multimeter, performance verification).

Source: Keithley Model DMM6500 Calibration and Adjustment Manual DMM6500-905-01 Rev. E (June 2022), section 2 'Performance verification' (printed pp. 2-2 to 2-48).
Every number below was read from RENDERED PAGE IMAGES (PyMuPDF, 105 dpi), page by page, not from extracted text (the extracted text scrambles the column order of the
digitize, DC current and resistance tables and drops the micro and ohm signs).  Adjustment (section 3, TSP command set only) is NOT built.

THE MANUAL DOES NOT PRINT ITS OWN LIMITS CHECK: the DMM6500 one-year accuracy specification is not in the Calibration manual or the Reference manual, so, unlike
the 2000 / 34410A builders, this script cannot recompute the limits from the data sheet.  What it does check, and stops on a disagreement it does not know:
  * every limit pair is symmetric about the nominal (or about the zero) in the unit printed;
  * the positive and the negative point of a range carry the same half-width;
  * known print problems are listed in KNOWN below and stored in the point as `flags` with the printed text in `printed_limits`.
PRINT PROBLEMS FOUND (each is listed again in the final report):
  * UNITS: the manual labels most tables '(A)', '(V)', '(Hz)', '(F)' while the numbers are in the range's own unit: digitize current setpoints and limits are in uA / mA / A
    by range (the 100 uA table prints 99.998 for 99.998 uA), the capacitance table is in nF for the nF ranges and uF for the uF ranges, the frequency table is Hz for the
    10 Hz row and kHz for the others.  Units here follow the range; the DC zero table (p. 2-43) prints no unit at all: uV is used (the 1000 V range zero is +/- 6 mV).
  * AC current 10 mA at 40 Hz / 1 kHz / 4.9 kHz (p. 2-38): the upper limit prints 10.14 mA, the lower 9.986 mA: 10.014 mA is used (the 1 A and 100 mA rows are +/- 0.14 %).
  * DC volts 100 V range, full scale (+) (p. 2-9): the lower limit prints 99.954 (a missing digit): 99.9954 is used. Its negative full scale prints +/- 0.0054 V against +/- 0.0046 V.
  * DC volts 1000 V range (p. 2-9): the negative full scale prints +/- 0.069 V against +/- 0.056 V for the positive full scale; the footnote adds 0.02 mV per volt above
    500 V.  Both are stored as printed.
  * The resistance tables (pp. 2-26, 2-27, 2-28) and the 4-wire 1 ohm / 10 ohm rows are marked 'for example only': limits must be calculated from the ACTUAL source
    value with the one-year accuracy spec, which this manual set does not contain.  The zero rows of those tables (-0.1 / 0.1 ... -10 / 10 with no consistent unit)
    disagree with the 4-wire-short table (p. 2-42) and are NOT built; the full-scale half-widths are taken from the example rows (printed limits minus the printed
    actual value, symmetric in every row) and are stored with std_relative = true: the limits are centred on the reference reading (reference DMM) or, without one,
    on the calibrator setting.  The 4-wire short table is built as printed (zero checks, 1 ohm to 100 kohm).
  * DC current 10 uA to 10 mA (pp. 2-31): the table lists the TOLERANCE (printed unit 'uA' for every range, meaning the range's own unit) about the reference-DMM reading;
    the 100 mA, 1 A and 3 A tables are limits about the calibrator setpoint (p. 2-33).  10 A (p. 2-45) is a limit about the nominal.
  * Digitize current: the 10 uA range is asked for in the steps (p. 2-34 step 5) but has no table: not built (owner decision 2026-11-04: leave it out; the data sheet SPEC-DMM6500
    Rev. A p. 9 lists digitize current accuracy for 100 uA to 10 A only, so there is no limit to build it from).  The setpoint column holds a typical reference value; the limit
    half-widths are constant per range and are used about the reference reading (or the calibrator setting).
  * AC volts and AC current at 20 Hz are below the 30 Hz-300 kHz range the manual quotes for the 30 Hz detector bandwidth: those points use bandwidth 3 (the specified
    one) and the rest 30 (the 40 Hz current points are inside the range).  Owner to confirm.
  * Figure 13 (p. 2-34) labels the meter 'Model DMM7510': a print leftover, the connections are the DMM6500's.
"""
import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'keithley_dmm6500_pv.json'
PERIOD = '1y'
DOC = 'Keithley Model DMM6500 Calibration and Adjustment Manual (DMM6500-905-01 Rev. E, June 2022)'
SCALE = {'uV': D('0.000001'), 'mV': D('0.001'), 'V': D(1), 'uA': D('0.000001'), 'mA': D('0.001'), 'A': D(1), 'ohm': D(1), 'kohm': D(1000), 'Mohm': D(1000000),
         'Hz': D(1), 'kHz': D(1000), 'nF': D('0.000000001'), 'uF': D('0.000001'), 'C': D(1)}

points_seen = []


def half(low, high, nominal, tag):
    """Half-width (Decimal, in the printed unit) of a printed limit pair about the nominal; stops if the pair is not symmetric."""
    lo, hi, nom = D(low), D(high), D(nominal)
    a, b = nom - lo, hi - nom
    if a != b:
        raise SystemExit(f'{tag}: the printed limits {low} / {high} are not symmetric about {nominal}')
    return a


def pt(ref, kind, nominal, rng, unit, lo, hi, group, page, desc, tag=None, frequency=None, rng_unit=None, **extra):
    """One point. nominal / lo / hi are the printed decimal strings in `unit`; the range is given in `rng_unit` (default `unit`); everything is stored in base units."""
    s = SCALE[unit]
    nom = D(nominal)
    h = half(lo, hi, nominal, f'{ref} {desc}') if lo is not None else None
    ru = SCALE[rng_unit or unit]
    p = dict(id=ref, kind=kind, desc=desc, nominal=float(nom * s), unit=unit, range=float(D(rng) * ru) if rng is not None else None, group=group, page=page, quick=False,
             limits={PERIOD: float(h * s)} if h is not None else {}, printed_limits=f'{lo} to {hi} {unit}' if lo is not None else '')
    if frequency is not None:
        p['frequency'] = float(frequency)
    p.update(extra)
    points_seen.append(p)
    return p


def mirror_check(points):
    """The positive and the negative point of a range must carry the same half-width (unless flagged)."""
    by = {}
    for p in points:
        if p.get('flags'):
            continue
        by.setdefault((p['kind'], p['range'], abs(p['nominal']), p.get('frequency')), set()).add(p['limits'].get(PERIOD))
    for key, widths in by.items():
        if len(widths) > 1:
            raise SystemExit(f'{key}: the positive and negative points disagree: {widths}')


def sym_points(prefix, kind, rng, unit, group, page, rows, rng_unit=None, **extra):
    """rows: [(label, nominal, lo, hi)] -> points."""
    out = []
    for n, (label, nominal, lo, hi) in enumerate(rows, 1):
        out.append(pt(f'{prefix}.{n}', kind, nominal, rng, unit, lo, hi, group, page, label, rng_unit=rng_unit, **extra))
    return out


def centred(ref, kind, nominal, rng, unit, lo, hi, group, page, desc, actual=None, tol_flags=None, **extra):
    """A limit pair printed about a reference value (example actual / typical reference): the half-width is (high - low) / 2 and the printed centre must be the actual
    value within the rounding of the last printed digit. Stored with std_relative = true (limits are centred on the reference reading, or on the source setting)."""
    h = (D(hi) - D(lo)) / 2
    if actual is not None:
        step = D(1).scaleb(min(D(lo).as_tuple().exponent, D(hi).as_tuple().exponent))
        if abs((D(hi) + D(lo)) / 2 - D(actual)) > step:
            raise SystemExit(f'{ref}: the printed centre {(D(hi) + D(lo)) / 2} is not the printed actual value {actual}')
    s = SCALE[unit]
    p = dict(id=ref, kind=kind, desc=desc, nominal=float(D(nominal) * s), unit=unit, range=float(D(rng) * s) if rng is not None else None, group=group, page=page, quick=False,
             limits={PERIOD: float(h * s)}, std_relative=True, printed_limits=f'{lo} to {hi} {unit}' + (f' about {actual}' if actual else ''), source='calibrator')
    if tol_flags:
        p['flags'] = tol_flags
    p.update(extra)
    points_seen.append(p)
    return p


def tolerance(ref, kind, nominal, rng, unit, tol, group, page, desc, **extra):
    """A printed tolerance (half-width) about the reference reading."""
    s = SCALE[unit]
    p = dict(id=ref, kind=kind, desc=desc, nominal=float(D(nominal) * s), unit=unit, range=float(D(rng) * s), group=group, page=page, quick=False, limits={PERIOD: float(D(tol) * s)},
             std_relative=True, printed_limits=f'+/- {tol} {unit}', source='calibrator')
    p.update(extra)
    points_seen.append(p)
    return p


def build_part2():
    out = []
    EX = 'the manual marks the table "for example only": the half-width is taken from the example row (printed limits minus the printed actual value); the limits are centred on the reference reading'
    # ---------------- 4-wire resistance (p. 2-24 .. 2-27), full-scale points; zero rows not built (see the module docstring) ---------------------------------
    ohm = [('1', 'ohm', '1', '0.999688', '1.000258', '0.999973', True, 'ohm'), ('10', 'ohm', '10', '9.99878', '10.00088', '9.99983', True, 'ohm'),
           ('100', 'ohm', '100', '99.987', '100.008', '99.9975', True, 'ohm'), ('1000', 'kohm', '1', '0.99991', '1.00007', '0.99999', True, 'kohm'),
           ('10000', 'kohm', '10', '9.99901', '10.00063', '9.99982', True, 'kohm'), ('100000', 'kohm', '100', '99.9928', '100.0098', '100.0012', False, 'kohm'),
           ('1000000', 'Mohm', '1', '0.99986', '1.000072', '0.999966', False, 'Mohm'), ('10000000', 'Mohm', '10', '9.99521', '10.00341', '9.99931', False, 'Mohm')]
    pts = []
    for rng, unit, nom, lo, hi, actual, ocomp, _ in ohm:
        label = {'ohm': 'ohm', 'kohm': 'kohm', 'Mohm': 'Mohm'}[unit]
        q = centred(f'OHM4.{rng}', 'OHM4', nom, D(rng) / SCALE[unit], unit, lo, hi, 'OHM4', '2-26' if ocomp else '2-27',
                    f'{nom} {label} on the {D(rng) / SCALE[unit]:g} {label} range', actual=actual, ocomp=ocomp, flags=[EX])
        pts.append(q)
    pts[5]['page'] = '2-27'
    out.append(dict(id='ohm4', title='4-wire resistance (1 ohm to 10 Mohm)', page='2-24 to 2-27', group='OHM4', source='calibrator', terminal='FRONT', optional=False, points=pts,
                    setup='Shielded Teflon-insulated 4-wire cable: INPUT and SENSE to the calibrator, calibrator in 4-wire (external sense ON). DMM6500: 4W Res, offset compensation ON and open-lead '
                          'detector OFF for 1 ohm to 10 kohm; offset compensation OFF for 100 kohm to 10 Mohm (10 Mohm: SENSE HI optional). The 1 ohm and 10 ohm values are characterised with the '
                          'reference DMM. Limits are about the reference reading (p. 2-24 to 2-27).'))
    pts = [centred('OHM2.100M', 'OHM2', '100', 100, 'Mohm', '99.798', '100.204', 'OHM2', '2-28', '100 Mohm on the 100 Mohm range (2-wire)', actual='100.001', flags=[EX])]
    out.append(dict(id='ohm2', title='2-wire resistance (100 Mohm)', page='2-27 to 2-28', group='OHM2', source='calibrator', terminal='FRONT', optional=False, points=pts,
                    setup='Calibrator in 2-wire (external sense OFF), shielded Teflon cables to INPUT HI / LO only. DMM6500: 2W Res, 100 Mohm range.'))

    # ---------------- DC current (p. 2-29 .. 2-33): 10 uA to 10 mA are tolerances about the reference DMM reading ---------------------------------------
    pts = []
    for rng, unit, rows in (('10', 'uA', (('10', '0.00500'), ('5', '0.00275'), ('-5', '0.00275'), ('-10', '0.00500'))),
                            ('100', 'uA', (('100', '0.0500'), ('50', '0.0275'), ('-50', '0.0275'), ('-100', '0.0500'))),
                            ('1', 'mA', (('1', '0.000500'), ('0.5', '0.000275'), ('-0.5', '0.000275'), ('-1', '0.000500'))),
                            ('10', 'mA', (('10', '0.00250'), ('5', '0.00150'), ('-5', '0.00150'), ('-10', '0.00250')))):
        for n, (nom, tol) in enumerate(rows, 1):
            pts.append(tolerance(f'DCI.{rng}{unit}.{n}', 'DCI', nom, rng, unit, tol, 'DCI_LOW', '2-31', f'{nom} {unit} on the {rng} {unit} range',
                                 flags=[f'the table prints the unit "uA" for every range; the range\'s own unit ({unit}) is used'] if unit == 'mA' else []))
    out.append(dict(id='dci_low', title='DC current 10 uA to 10 mA (reference DMM)', page='2-29 to 2-31', group='DCI_LOW', source='calibrator', terminal='FRONT', optional=False, points=pts,
                    setup='Calibrator, reference DMM (8508A / 8588A 200 uA range for 10 uA and 100 uA; 2 mA / 20 mA ranges for 1 mA / 10 mA) and the DMM6500 in series. Zero the reference DMM for system '
                          'offset first; relative offset on the DMM6500 disabled. Limits are the printed tolerance about the reference DMM reading (p. 2-30, 2-31). The zero-current check '
                          'needs the cables removed (separate set-up); its limit is not printed and it is not built.'))
    pts = []
    for rng, unit, rows in (('100', 'mA', (('100', '99.975', '100.025'), ('50', '49.985', '50.015'), ('-50', '-50.015', '-49.985'), ('-100', '-100.025', '-99.975'))),
                            ('1', 'A', (('1', '0.99955', '1.00045'), ('0.5', '0.49975', '0.50025'), ('-0.5', '-0.50025', '-0.49975'), ('-1', '-1.00045', '-0.99955'))),
                            ('3', 'A', (('2', '1.99888', '2.00112'), ('1.5', '1.49913', '1.50087'), ('-1.5', '-1.50087', '-1.49913'), ('-2', '-2.00112', '-1.99888')))):
        for n, (nom, lo, hi) in enumerate(rows, 1):
            q = pt(f'DCI.{rng}{unit}.{n}', 'DCI', nom, rng, unit, lo, hi, 'DCI', '2-33', f'{nom} {unit} on the {rng} {unit} range', source='calibrator',
                   flags=['the table prints "(A)" for the 100 mA range; values are in mA'] if unit == 'mA' else (['3 A range full scale is 2 A: the Fluke 57xxA / 5725A are not accurate above 2.2 A'] if rng == '3' and n in (1, 4) else []))
            pts.append(q)
    out.append(dict(id='dci', title='DC current 100 mA to 3 A', page='2-32 to 2-33', group='DCI', source='calibrator', terminal='FRONT', optional=False, points=pts,
                    setup='Calibrator current output to AMPS 3A and INPUT LO. Zero verify with the calibrator in STANDBY first (no limit printed: not built); then the table values for each range.'))

    # ---------------- Digitize current (p. 2-33 .. 2-36), half-widths about the reference value ----------------------------------------------------------
    dci = [('100', 'uA', (('99.998', '99.878', '100.118'), ('49.9991', '49.9141', '50.0841'), ('-49.993', '-50.0843', '-49.9143'), ('-99.9985', '-100.1185', '-99.8785')), ('100', '50', '-50', '-100')),
           ('1', 'mA', (('0.999993', '0.998993', '1.000993'), ('0.499998', '0.499348', '0.500648'), ('-0.500009', '-0.500659', '-0.499359'), ('-1.000017', '-1.001017', '-0.999017')), ('1', '0.5', '-0.5', '-1')),
           ('10', 'mA', (('10.00004', '9.99204', '10.00804'), ('5.00004', '4.99454', '5.00554'), ('-5.00003', '-5.00553', '-4.99453'), ('-10.00006', '-10.00806', '-9.99206')), ('10', '5', '-5', '-10')),
           ('100', 'mA', (('100', '99.92', '100.08'), ('50', '49.945', '50.055'), ('-50', '-50.055', '-49.945'), ('-100', '-100.08', '-99.92')), ('100', '50', '-50', '-100')),
           ('1', 'A', (('1', '0.999', '1.001'), ('0.5', '0.49935', '0.50065'), ('-0.5', '-0.50065', '-0.49935'), ('-1', '-1.001', '-0.999')), ('1', '0.5', '-0.5', '-1')),
           ('3', 'A', (('2', '1.997', '2.003'), ('1.5', '1.49745', '1.50255'), ('-1.5', '-1.50255', '-1.49745'), ('-2', '-2.003', '-1.997')), ('2', '1.5', '-1.5', '-2'))]
    pts = []
    for rng, unit, rows, noms in dci:
        for n, ((actual, lo, hi), nom) in enumerate(zip(rows, noms), 1):
            fl = ['the setpoint column holds a typical reference value; the unit label "(A)" is the range\'s own unit']
            if rng == '100' and unit == 'uA' and n == 3:
                fl.append('the printed setpoint -49.993 is -49.9993 about the printed limits (centre); the printed limits are used')
            q = dict(centred(f'DIGI.{rng}{unit}.{n}', 'DIGI', nom, rng, unit, lo, hi, 'DIGI', '2-34' if rng == '100' and unit == 'uA' else '2-35' if (rng, unit) != ('3', 'A') else '2-36',
                             f'{nom} {unit} on the {rng} {unit} range (digitize)', actual=None, tol_flags=fl, srate=1000, count=100, aperture=0.001, statistic='average'))
            pts.append(q)
    out.append(dict(id='digi', title='Digitize current 100 uA to 3 A', page='2-33 to 2-36', group='DIGI', source='calibrator', terminal='FRONT', optional=False, points=pts,
                    setup='DMM6500: Digitize Current, sample rate 1000, aperture Auto (1 ms here), count 100; the reading is the average of the 100 readings. Calibrator current output to AMPS 3A and INPUT '
                          'LO. The 10 uA digitize range is asked for in step 5 but has no table: not built.'))

    # ---------------- AC current (p. 2-36 .. 2-38) ----------------------------------------------------------------------------------------------------
    aci = [('100', 'uA', '100', '0.17', (20, 1000)), ('1', 'mA', '1', '0.0014', (20, 1000, 4900)), ('10', 'mA', '10', '0.014', (40, 1000, 4900)), ('100', 'mA', '100', '0.14', (40, 1000, 4900)),
           ('1', 'A', '1', '0.0014', (40, 1000, 4900)), ('3', 'A', '2', '0.0048', (40, 1000, 4900))]
    pts = []
    for rng, unit, nom, h, freqs in aci:
        for f in freqs:
            fl = []
            if (rng, unit) == ('10', 'mA'):
                fl.append('printed 9.986 to 10.14 mA; 10.014 mA is used for the upper limit (print error, 1 A row is +/- 0.14 %)')
            q = pt(f'ACI.{rng}{unit}.{f}', 'ACI', nom, rng, unit, str(D(nom) - D(h)), str(D(nom) + D(h)), 'ACI', '2-37' if rng in ('100', '1') and unit in ('uA', 'mA') else '2-38',
                   f'{nom} {unit} at {f} Hz on the {rng} {unit} range', frequency=f, source='calibrator', ac_bandwidth=3 if f < 30 else 30, flags=fl)
            pts.append(q)
    out.append(dict(id='aci', title='AC current 100 uA to 3 A', page='2-36 to 2-38', group='ACI', source='calibrator', terminal='FRONT', optional=False, points=pts,
                    setup='DMM6500: AC Current, detector bandwidth 30 Hz (3 Hz for 20 Hz, UNVERIFIED choice). Calibrator AC current output to AMPS 3A and INPUT LO.'))

    # ---------------- Rear panel 10 A (p. 2-43 .. 2-48) ---------------------------------------------------------------------------------------------------
    pts = [pt(f'DCI.10A.{n}', 'DCI', nom, 10, 'A', lo, hi, 'REAR10A', '2-45', f'{nom} A on the 10 A range', source='calibrator', terminal='REAR')
           for n, (nom, lo, hi) in enumerate((('10', '9.9755', '10.0245'), ('5', '4.9865', '5.0135'), ('-5', '-5.0135', '-4.9865'), ('-10', '-10.0245', '-9.9755')), 1)]
    pts += [pt(f'DIGI.10A.{n}', 'DIGI', nom, 10, 'A', lo, hi, 'REAR10A', '2-46', f'{label} on the 10 A range (digitize)', source='none' if nom == '0' else 'calibrator', terminal='REAR', srate=1000, count=100,
               aperture=0.001, statistic='average')
            for n, (label, nom, lo, hi) in enumerate((('UUT zero', '0', '-0.008', '0.008'), ('10 A', '10', '9.967', '10.033'), ('5 A', '5', '4.9795', '5.0205'), ('-5 A', '-5', '-5.0205', '-4.9795'),
                                                      ('-10 A', '-10', '-10.033', '-9.967')), 1)]
    pts += [pt(f'ACI.10A.{f}', 'ACI', '10', 10, 'A', '9.954', '10.046', 'REAR10A', '2-48', f'10 A at {f} Hz', frequency=f, source='calibrator', terminal='REAR', ac_bandwidth=30) for f in (40, 1000, 4900)]
    out.append(dict(id='rear10a', title='Rear-panel 10 A range (DC, digitize, AC)', page='2-43 to 2-48', group='REAR10A', source='calibrator', terminal='REAR', optional=False, points=pts,
                    setup='TERMINALS switch to REAR. Calibrator with its current amplifier (5725A, BOOST, range lock ON): amplifier OUTPUT HI to the 10A AMPS jack, OUTPUT LO to INPUT LO; heavy short '
                          'cables. DC: relative offset applied with the calibrator in STANDBY, the DMM6500 zero reading is verified (no limit printed: not built), reference DMM readings recorded.'))

    # ---------------- Capacitance (p. 2-39 .. 2-41): nF ranges in nF, uF ranges in uF -------------------------------------------------------------------
    cap = [('1 nF range cable REL', 'nF', '0.375', '0.25', '0.5', 1), ('10% 1 nF range', 'nF', '0.1', '0.0942', '0.1058', 1), ('70% 1 nF range', 'nF', '0.7', '0.6894', '0.7106', 1),
           ('10% 10 nF range', 'nF', '1', '0.986', '1.014', 10), ('100% 10 nF range', 'nF', '10', '9.95', '10.05', 10), ('10% 100 nF range', 'nF', '10', '9.86', '10.14', 100),
           ('100% 100 nF range', 'nF', '100', '99.5', '100.5', 100), ('10% 1 uF range', 'uF', '0.1', '0.0986', '0.1014', 1), ('100% 1 uF range', 'uF', '1', '0.995', '1.005', 1),
           ('10% 10 uF range', 'uF', '1', '0.986', '1.014', 10), ('100% 10 uF range', 'uF', '10', '9.95', '10.05', 10), ('10% 100 uF range', 'uF', '10', '9.86', '10.14', 100),
           ('100% 100 uF range', 'uF', '100', '99.5', '100.5', 100)]
    pts = []
    for n, (label, unit, nom, lo, hi, rng) in enumerate(cap, 1):
        fl = ['the table prints "(F)"; nF for the nF ranges and uF for the uF ranges']
        if n == 1:
            fl.append('the cable-only reading (no source, calibrator in standby): the limits 0.25 to 0.5 nF are the cable capacitance the manual expects; the relative offset is acquired from it and kept for the '
                      'other capacitance points (steps 6-8, p. 2-39). The calibrator terminal capacitance is part of this reading: UNVERIFIED that it stays inside 0.25 to 0.5 nF')
        if n == 2:
            fl.append('0.1 nF is below the lowest capacitance the calibrators may be able to source: check the calibrator range (UNVERIFIED), the point is refused by the calibrator if it cannot be made')
        pts.append(pt(f'CAP.{n}', 'CAP', nom, rng, unit, lo, hi, 'CAP', '2-41', label, source='none' if n == 1 else 'calibrator', flags=fl, **({'rel_acquire': True, 'input': 'open'} if n == 1 else {})))
    out.append(dict(id='cap', title='Capacitance (1 nF to 100 uF)', page='2-39 to 2-41', group='CAP', source='calibrator', terminal='FRONT', optional=False, points=pts,
                    setup='Owner decision: the calibrator sources the capacitance (the manual uses IET decade boxes). Short shielded banana cable from the calibrator output to INPUT HI / LO (cable capacitance up to '
                          'about 300 pF: keep it short). DMM6500 Capacitance on the 1 nF range: first the cable-only reading with the calibrator in standby, then Rel Acquire (kept for the rest), then each value.'))
    return out


def build():
    sections = []

    # ---------------- DC volts, p. 2-8 / 2-9 (front terminals), 100 mV range first --------------------------------------------------------------------------
    dcv = [
        ('0.1', 'mV', '2-8', [('Full scale (+)', '100', '99.9935', '100.0065'), ('Half scale (+)', '50', '49.995', '50.005'), ('Half scale (-)', '-50', '-50.005', '-49.995'),
                              ('Full scale (-)', '-100', '-100.0065', '-99.9935')]),
        ('1', 'V', '2-8', [('Full scale (+)', '1', '0.999969', '1.000031'), ('Half scale (+)', '0.5', '0.499979', '0.500021'), ('Half scale (-)', '-0.5', '-0.500021', '-0.499979'),
                           ('Full scale (-)', '-1', '-1.000031', '-0.999969')]),
        ('10', 'V', '2-8', [('Full scale (+)', '10', '9.9997', '10.0003'), ('Half scale (+)', '5', '4.99982', '5.00018'), ('Half scale (-)', '-5', '-5.00018', '-4.99982'),
                            ('Full scale (-)', '-10', '-10.0003', '-9.9997')]),
        ('100', 'V', '2-9', [('Full scale (+)', '100', '99.9954', '100.0046'), ('Half scale (+)', '50', '49.99685', '50.00315'), ('Half scale (-)', '-50', '-50.00315', '-49.99685'),
                             ('Full scale (-)', '-100', '-100.0054', '-99.9946')]),
    ]
    pts = [pt('DCV.0', 'DCV', '0', '0.1', 'mV', '-0.01', '0.01', 'DCV', '2-8', 'Relative offset (100 mV range, calibrator at 0 V)', rng_unit='V', source='calibrator', rel_zero=True)]
    pts[0]['range'] = 0.1
    for rng, unit, page, rows in dcv:
        for n, (label, nominal, lo, hi) in enumerate(rows, 1):
            q = pt(f'DCV.{rng}.{n}', 'DCV', nominal, None, unit, lo, hi, 'DCV', page, f'{label} {rng} {"V" if rng != "0.1" else "mV"} range', source='calibrator')
            q['range'] = float(D(rng))
            if q['id'] == 'DCV.100.1':
                q['flags'] = ['printed lower limit 99.954 is a missing digit: 99.9954 is used (the upper limit prints 100.0046); the negative full scale prints +/- 0.0054 V against +/- 0.0046 V here']
                q['printed_limits'] = '99.954 to 100.0046 V'
            elif q['id'] == 'DCV.100.4':
                q['flags'] = ['the negative full scale prints +/- 0.0054 V against +/- 0.0046 V for the positive full scale; stored as printed']
            pts.append(q)
    r1000 = [('Full scale (+)', '1000', '999.944', '1000.056'), ('Half scale (+)', '500', '499.974', '500.026'), ('Half scale (-)', '-500', '-500.026', '-499.974'),
             ('Full scale (-)', '-1000', '-1000.069', '-999.931')]
    for n, (label, nominal, lo, hi) in enumerate(r1000, 1):
        q = pt(f'DCV.1000.{n}', 'DCV', nominal, 1000, 'V', lo, hi, 'DCV', '2-9', f'{label} 1000 V range', source='calibrator')
        if n == 4:
            q['flags'] = ['printed +/- 0.069 V against +/- 0.056 V for the positive full scale (footnote: add 0.02 mV per volt above +/- 500 V); stored as printed']
        pts.append(q)
    mirror_check(pts)
    sections.append(dict(id='dcv', title='DC voltage', page='2-6 to 2-9', group='DCV', source='calibrator', terminal='FRONT', optional=False, points=pts,
                         setup='Low-thermal cable, shield to the calibrator output LO (100 mV and 1 V ranges). DMM6500: DC voltage, input impedance Auto. Calibrator at 0 V in operate, '
                               'allow 5 minutes of thermal settling, enable relative offset on the 100 mV range, then source the full-scale and half-scale values of each range, '
                               'allowing the reading to settle (p. 2-7, 2-8).'))

    # ---------------- AC volts, p. 2-12 / 2-14 (the limits are in the range's unit) ------------------------------------------------------------------------
    acv = [('0.1', 'mV', '100', {'20 Hz': ('99.91', '100.09'), '1 kHz': ('99.91', '100.09'), '50 kHz': ('99.83', '100.17'), '100 kHz': ('99.32', '100.68')}),
           ('1', 'V', '1', {'20 Hz': ('0.9991', '1.0009'), '1 kHz': ('0.9991', '1.0009'), '50 kHz': ('0.9983', '1.0017'), '100 kHz': ('0.9932', '1.0068')}),
           ('10', 'V', '10', {'20 Hz': ('9.991', '10.009'), '1 kHz': ('9.991', '10.009'), '50 kHz': ('9.983', '10.017'), '100 kHz': ('9.932', '10.068')}),
           ('100', 'V', '100', {'20 Hz': ('99.91', '100.09'), '1 kHz': ('99.91', '100.09'), '50 kHz': ('99.83', '100.17'), '100 kHz': ('99.32', '100.68')})]
    HZ = {'20 Hz': 20, '50 Hz': 50, '1 kHz': 1000, '50 kHz': 50000, '100 kHz': 100000}
    pts = []
    for rng, unit, nom, rows in acv:
        for freq, (lo, hi) in rows.items():
            q = pt(f'ACV.{rng}.{freq.replace(" ", "")}', 'ACV', nom, None, unit, lo, hi, 'ACV', '2-12', f'{nom} {unit} at {freq}', frequency=HZ[freq], source='calibrator',
                   ac_bandwidth=3 if HZ[freq] < 30 else 30)
            q['range'] = float(D(rng))
            pts.append(q)
    for freq, (lo, hi) in {'50 Hz': ('739.33', '740.67'), '1 kHz': ('739.33', '740.67'), '50 kHz': ('738.66', '741.34'), '100 kHz': ('734.96', '745.04')}.items():
        pts.append(pt(f'ACV.750.{freq.replace(" ", "")}', 'ACV', '740', 750, 'V', lo, hi, 'ACV750', '2-14', f'740 V at {freq}', frequency=HZ[freq], source='calibrator',
                      ac_bandwidth=30, note='50 kHz and 100 kHz: the manual uses a Fluke 5725A amplifier behind the calibrator' if HZ[freq] >= 50000 else ''))
    sections.append(dict(id='acv', title='AC voltage', page='2-10 to 2-14', group='ACV', source='calibrator', terminal='FRONT', optional=False, points=pts,
                         setup='Shielded low-capacitance cable (load below 1000 pF on the 100 mV to 100 V ranges, below 150 pF on 750 V). DMM6500: AC voltage, detector bandwidth 30 Hz '
                               '(3 Hz for the 20 Hz points, UNVERIFIED choice). The 740 V points: calibrator in standby while connecting (p. 2-13).'))

    # ---------------- Digitize DC voltage, p. 2-14 .. 2-16 -----------------------------------------------------------------------------------------------
    dig = [('0.1', 'mV', [('Full scale (+)', '100', '99.94', '100.06'), ('Half scale (+)', '50', '49.95', '50.05'), ('Half scale (-)', '-50', '-50.05', '-49.95'), ('Full scale (-)', '-100', '-100.06', '-99.94')]),
           ('1', 'V', [('Full scale (+)', '1', '0.9996', '1.0004'), ('Half scale (+)', '0.5', '0.49975', '0.50025'), ('Half scale (-)', '-0.5', '-0.50025', '-0.49975'), ('Full scale (-)', '-1', '-1.0004', '-0.9996')]),
           ('10', 'V', [('Full scale (+)', '10', '9.996', '10.004'), ('Half scale (+)', '5', '4.9975', '5.0025'), ('Half scale (-)', '-5', '-5.0025', '-4.9975'), ('Full scale (-)', '-10', '-10.004', '-9.996')]),
           ('100', 'V', [('Full scale (+)', '100', '99.96', '100.04'), ('Half scale (+)', '50', '49.975', '50.025'), ('Half scale (-)', '-50', '-50.025', '-49.975'), ('Full scale (-)', '-100', '-100.04', '-99.96')]),
           ('1000', 'V', [('Full scale (+)', '1000', '999.6', '1000.4'), ('Half scale (+)', '500', '499.75', '500.25'), ('Half scale (-)', '-500', '-500.25', '-499.75'), ('Full scale (-)', '-1000', '-1000.4', '-999.6')])]
    pts = []
    for rng, unit, rows in dig:
        for n, (label, nominal, lo, hi) in enumerate(rows, 1):
            q = pt(f'DIGV.{rng}.{n}', 'DIGV', nominal, None, unit, lo, hi, 'DCV', '2-16', f'{label} digitize {rng} {unit if unit == "mV" else "V"} range', source='calibrator',
                   srate=1000, count=100, aperture=0.001, statistic='average')
            q['range'] = float(D(rng))
            pts.append(q)
    mirror_check(pts)
    sections.append(dict(id='digv', title='Digitize DC voltage', page='2-14 to 2-16', group='DCV', source='calibrator', terminal='FRONT', optional=False, points=pts,
                         setup='DMM6500: Digitize Voltage, sample rate 1000, aperture Auto (1 ms here), count 100. Calibrator at 0.00000 mV and settled first; each reading is the AVERAGE of the 100 '
                               'digitized readings (the STATISTICS swipe screen). The 5720A / 5730A 1000 V range 0 V setting is not verified (p. 2-15).'))

    # ---------------- Frequency, p. 2-17 / 2-18 ---------------------------------------------------------------------------------------------------------
    fq = [('10 Hz at 10 V', 'Hz', '10', '9.997', '10.003', 10, 10), ('1 kHz at 5 V', 'kHz', '1', '0.9999', '1.0001', 1000, 5), ('10 kHz at 5 V', 'kHz', '10', '9.9991', '10.0009', 10000, 5),
          ('100 kHz at 5 V', 'kHz', '100', '99.991', '100.009', 100000, 5), ('300 kHz at 5 V', 'kHz', '300', '299.973', '300.027', 300000, 5)]
    pts = []
    for n, (label, unit, nom, lo, hi, hz, volts) in enumerate(fq, 1):
        pts.append(pt(f'FREQ.{n}', 'FREQ', nom, None, unit, lo, hi, 'FREQ', '2-18', label, frequency=hz, amplitude=volts, source='generator',
                      flags=['the manual prints the column header (Hz) but the 1 kHz to 300 kHz rows are in kHz; read in kHz'] if unit == 'kHz' else []))
    sections.append(dict(id='freq', title='Frequency', page='2-17 to 2-18', group='FREQ', source='generator', terminal='FRONT', optional=False, points=pts,
                         setup='The manual uses a Keithley 3390 function generator on INPUT HI / LO. DMM6500: Frequency, aperture 250 ms, threshold range 10 V. Sine at the listed amplitude (RMS '
                               'amplitude not stated: UNVERIFIED, 10 V at 10 Hz and 5 V above).'))

    # ---------------- Simulated thermocouple type J, p. 2-18 .. 2-20 ------------------------------------------------------------------------------------
    pts = [pt('TC.1', 'TEMP', '-190', None, 'C', '-190.2', '-189.8', 'TC', '2-20', 'Type J, -190 degC', source='calibrator', source_value=-0.007659, source_unit='V', transducer='TC',
              tc_type='J'),
           pt('TC.2', 'TEMP', '0', None, 'C', '-0.2', '0.2', 'TC', '2-20', 'Type J, 0 degC', source='calibrator', source_value=0.0, source_unit='V', transducer='TC', tc_type='J'),
           pt('TC.3', 'TEMP', '750', None, 'C', '749.8', '750.2', 'TC', '2-20', 'Type J, 750 degC', source='calibrator', source_value=0.042281, source_unit='V', transducer='TC', tc_type='J')]
    sections.append(dict(id='tc', title='Simulated thermocouple (type J)', page='2-18 to 2-20', group='TC', source='calibrator', terminal='FRONT', optional=False, points=pts,
                         setup='Source values are the NIST Monograph 175 type J voltages (-7.659 mV, 0 mV, 42.281 mV). First measure the cable offset: DMM6500 DC voltage, 100 mV range, input impedance '
                               'Auto, autozero on, 1 PLC, calibrator at 0 V in operate, wait 5 minutes, record the offset to 1 uV; then DMM6500 Temperature, transducer TC, type J, simulated '
                               'reference junction 0 degC, 1 PLC, autozero on, and set the calibrator to the table value MINUS the measured offset (p. 2-19, 2-20 step 19).'))

    # ---------------- Simulated RTD PT100, p. 2-20 .. 2-24 -------------------------------------------------------------------------------------------------
    pts = []
    for wires, tol, tr in ((4, '0.06', 'FRTD'), (3, '0.75', 'TRTD')):
        for n, (ohms, rows) in enumerate((('19', '-198.8900'), ('100', '-0.0075'), ('190', '238.6775')), 1):
            q = dict(id=f'RTD{wires}.{n}', kind='TEMP', desc=f'PT100 {wires}-wire, {ohms} ohm', nominal=float(D(ohms)), unit='ohm', range=None, group=f'RTD{wires}', page='2-24', quick=False,
                     limits={PERIOD: float(D(tol))}, limit_unit='C', printed_limits=f'+/- {tol} degC', source='calibrator', source_value=float(D(ohms)), source_unit='ohm', transducer=tr, rtd='PT100',
                     std_relative=True, example_temperature=float(D(rows)), cvd=dict(R0=100, alpha='0.00385055', beta='0.10863', delta='1.4999'))
            points_seen.append(q)
            pts.append(q)
    sections.append(dict(id='rtd', title='Simulated RTD (PT100)', page='2-20 to 2-24', group='RTD', source='calibrator', terminal='FRONT', optional=False, points=pts,
                         setup='Calibrator resistance 19, 100 and 190 ohm with EXTERNAL SENSE on (4-wire: INPUT and SENSE to the calibrator; 3-wire: SENSE HI not required, HI-LO lead resistance '
                               'mismatch below 0.1 ohm, add 0.25 degC per 0.1 ohm). DMM6500: Temperature, transducer 4-wire RTD or 3-wire RTD, RTD type PT100. The expected temperature is the '
                               'Callendar-Van Dusen value of the ACTUAL source resistance (R0 100, alpha 0.00385055, beta 0.10863, delta 1.4999, ITS-90); limit +/- 0.06 degC (4-wire) or '
                               '+/- 0.75 degC (3-wire) about it (p. 2-21 to 2-24).'))

    # ---------------- 4-wire short zeros, p. 2-42 / 2-43 (optional: not in the customer report) -------------------------------------------------
    pts = []
    for ref, rng, lim in (('ZR.1', 1, '0.0002'), ('ZR.10', 10, '0.0002'), ('ZR.100', 100, '0.002'), ('ZR.1k', 1000, '0.006'), ('ZR.10k', 10000, '0.06'), ('ZR.100k', 100000, '1')):
        q = dict(id=ref, kind='OHM4', desc=f'4-wire short, {rng} ohm range', nominal=0.0, unit='ohm', range=float(rng), group='SHORT4', page='2-42', quick=False, limits={PERIOD: float(D(lim))},
                 printed_limits=f'-{lim} to {lim} ohm', source='none', input='short', ocomp=True)
        points_seen.append(q)
        pts.append(q)
    for ref, rng, lim in (('ZV.1000', 1000, '6000'), ('ZV.100', 100, '600'), ('ZV.10', 10, '50'), ('ZV.1', 1, '6'), ('ZV.0.1', 0.1, '3.5')):
        q = dict(id=ref, kind='DCV', desc=f'DC volts zero, 4-wire short, {rng} V range', nominal=0.0, unit='uV', range=float(rng), group='SHORT4', page='2-43', quick=False,
                 limits={PERIOD: float(D(lim) * SCALE['uV'])}, printed_limits=f'-{lim} to {lim} (unit not printed: uV)', source='none', input='short',
                 flags=['the table prints no unit; microvolts used (the 1000 V range zero would otherwise be +/- 6000 V)'])
        points_seen.append(q)
        pts.append(q)
    sections.append(dict(id='short4', title='Zero values with the 4-wire short', page='2-41 to 2-43', group='SHORT4', source='none', terminal='FRONT', optional=True, points=pts,
                         setup='Model 8610 or 8620 4-wire short on the front panel in the orientation of Figure 17 (p. 2-42), 4W Res with offset compensation ON, 1 ohm range first, allow 5 minutes, '
                               'no relative offset; then DC volts in DESCENDING range order from 1000 V to 100 mV with the short left on. Not part of the Customer Calibration Data Report (p. 2-41), '
                               'so optional.'))

    sections += build_part2()
    for s in sections:
        mirror_check([p for p in s['points'] if p['kind'] != 'TEMP'])
    return dict(schema=1, manufacturer='Keithley', model='DMM6500', title='DMM6500 Performance Verification',
                idn_match=['DMM6500'], source=dict(document=DOC, pages='2-6 to 2-48', note='ONE interval: 1 year, 18-28 C (ambient within 5 C of TCAL), calculated from the one-year specification '
                                                   'without test-equipment uncertainty (p. 2-4). The DMM6500 data sheet is not in the manual set, so the limits cannot be recomputed here.'),
                periods=[PERIOD], default_period=PERIOD, front_rear_switch=True,
                equipment=dict(calibrator='Fluke 5720A / 5730A (+ 5725A for 750 V above 20 kHz) in the manual; this procedure drives the lab calibrator',
                               frequency='Keithley 3390 function generator in the manual'),
                general=['Warm up the DMM6500 for at least 30 minutes (p. 2-2); 18 to 28 C, relative humidity 80 % or less, no direct airflow on the input terminals.',
                         'Restore factory defaults first (MENU > Info/Manage > System Reset, p. 2-6); the program sends *RST and tells the operator.',
                         'Do not connect through a scanner or other switching equipment (p. 2-6). Terminals rated CAT II 300 V; 1000 V dc / 750 V ac maximum input; 500 V peak to chassis.'],
                sections=sections)


def main():
    spec = build()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=True) + '\n', encoding='utf-8')
    total = sum(len(s['points']) for s in spec['sections'])
    print(f'wrote {OUT.name}: {total} points in {len(spec["sections"])} sections')


if __name__ == '__main__':
    main()
