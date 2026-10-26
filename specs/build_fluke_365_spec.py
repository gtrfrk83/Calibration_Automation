"""Builds specs/fluke_365_pv.json for the shared handheld engine (handheld_dmm.py, through fluke365_verification.py) from the Fluke 365
Detachable Jaw True-rms Clamp Meter Calibration Manual (R0, 20 PDF pages).

    python3 specs/build_fluke_365_spec.py

Source (printed page numbers; the PDF page is the printed page + 8):
  Table 2 "Performance Tests", printed p. 7 (AC volts, DC volts, ohms) and p. 8 (AC amps and DC amps "with 20 turn coil"), 32 points;
  Electrical Specifications, printed pp. 5-6 (range, resolution, accuracy of every function);
  Safety Information, printed pp. 2-3 (do not measure current with the test leads in the jacks; 30 V ac rms / 42 V ac peak / 60 V dc shock level);
  Table 3 "Required Equipment" (printed p. 8: calibrator 4.5 digit resolution, Fluke 55xxA recommended; wired coil, 20 turns).
Every nominal, frequency and limit below was read from the RENDERED PAGE IMAGES (pdftoppm at 170 and 260 dpi), twice, never from extracted text.

What Table 2 means for the current rows: the "Calibrator Output" is the current the CALIBRATOR drives through the 20-turn coil, and the limits are what the
METER reads (20 x the calibrator current): .5 A -> 9.6 .. 10.4 A, 5 A -> 98.7 .. 101.3 A, 9.5 A -> 187.5 .. 192.5 A.  So each current point has
applied.value = the calibrator output (0.5 / 5 / 9.5 A) and nominal = what the meter should show (10 / 100 / 190 A).

Cross-check against the published specification (printed p. 5):  limit = +/-(% of reading + 5 digits), % = 1.5 (AC V), 1 (DC V, ohms), 2 (DC A, AC A
45-65 Hz), 2.5 (AC A 65-400 Hz).  Every printed limit that is not at zero is HALF of that specification (the manual's test limits keep a 2:1 margin); the builder
recomputes the half-width of every row in Decimal and lists each row that is not within half a display step of it.  NOTHING is changed: the printed limits are
what the procedure judges; each disagreement is stored in the step ('check') and shown in the point note, and printed by the builder.  The builder aborts only if
a printed limit is LOOSER than the full published specification.
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_365_pv.json'
MODEL = '365'
TABLE = '2'
DOCUMENT = 'Fluke 365 Detachable Jaw True-rms Clamp Meter - Calibration Manual (R0, 2010)'

# display unit -> (factor to base unit, base unit); nothing in Table 2 uses a prefixed unit
UNITS = {'V': ('1', 'V'), 'Ω': ('1', 'ohm'), 'A': ('1', 'A')}

# Rotary switch text ('short  (detail)': the engine asks again whenever this text changes between two points).  The manual's Figure 1 draws the switch
# positions as symbols only and Table 2 names them 'AC Volts', 'DC Volts', 'Ohms' (with the continuity symbol above the Ohm sign), 'AC Amps', 'DC Amps':
# the ORDER of the positions around the dial is not read from the manual (UNVERIFIED).
SW = {
    'acv': 'V~  (AC volts)',
    'dcv': 'V⎓  (DC volts)',
    'ohm': 'Ω  (ohms; the position shared with continuity)',
    'aca': 'A~  (AC amps, detachable jaw on the 20-turn coil)',
    'dca': 'A⎓  (DC amps, detachable jaw on the 20-turn coil)',
}

# published specification, printed p. 5: (percent of reading, counts) and the resolution of the range the reading falls in
ACC = {'ACV': ('1.5', 5), 'DCV': ('1', 5), 'OHM': ('1', 5), 'DCI': ('2', 5), 'ACI50': ('2', 5), 'ACI400': ('2.5', 5)}

NOTE_OHMS = 'Table 2 does not say whether the limits include test lead resistance (UNVERIFIED).'
NOTE_OHM_ZERO = ('At 0 ohm the whole 0.3 ohm upper limit is in play, so use the shortest leads; the lower limit is printed 0 (the meter cannot read below zero), '
                 'the specification would allow -0.5 ohm.')
NOTE_COIL = ('The calibrator drives the 20-turn coil and the meter reads 20 x the calibrator current: {applied} A in, {nominal} A on the meter. '
             'The limits are the meter readings (Table 2, printed p. 8). '
             'Uncertainty (owner-chosen convention): the regular calibrator current uncertainty at the calibrator output current ({applied} A), as it is, NOT multiplied by 20 and without the coil; '
             'TAR / TUR compare that unscaled value with the meter-reading tolerance printed in Table 2.')

# (section, switch key, range, kind, applied (calibrator output, base units), frequency (Hz or None), display unit, nominal (what the meter shows, display unit),
#  printed low, printed high (exactly as printed), accuracy key, resolution of the range)
ROWS = [
    ('AC volts', 'acv', '600.0 V', 'ACV', '30', 50, 'V', '30', '29.5', '30.5', 'ACV', '0.1'),
    ('AC volts', 'acv', '600.0 V', 'ACV', '300', 50, 'V', '300', '297.5', '302.5', 'ACV', '0.1'),
    ('AC volts', 'acv', '600.0 V', 'ACV', '570', 50, 'V', '570', '565.5', '574.5', 'ACV', '0.1'),
    ('AC volts', 'acv', '600.0 V', 'ACV', '30', 400, 'V', '30', '29.5', '30.5', 'ACV', '0.1'),
    ('AC volts', 'acv', '600.0 V', 'ACV', '300', 400, 'V', '300', '297.5', '302.5', 'ACV', '0.1'),
    ('AC volts', 'acv', '600.0 V', 'ACV', '570', 400, 'V', '570', '565.5', '574.5', 'ACV', '0.1'),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '0', None, 'V', '0', '-0.3', '0.3', 'DCV', '0.1'),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '30', None, 'V', '30', '29.6', '30.4', 'DCV', '0.1'),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '300', None, 'V', '300', '298.2', '301.8', 'DCV', '0.1'),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '570', None, 'V', '570', '566.9', '573.1', 'DCV', '0.1'),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '-30', None, 'V', '-30', '-30.4', '-29.6', 'DCV', '0.1'),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '-300', None, 'V', '-300', '-301.8', '-298.2', 'DCV', '0.1'),
    ('DC volts', 'dcv', '600.0 V', 'DCV', '-570', None, 'V', '-570', '-573.1', '-566.9', 'DCV', '0.1'),
    # Table 2 names no range for the ohms points: the resolution rule is p. 5 (600.0 ohm range, 0.1 ohm; 6000 ohm range, 1 ohm), so 900 ohm and up read on 6000 ohm
    ('Ohms', 'ohm', '600.0 Ω', 'OHM', '0', None, 'Ω', '0', '0', '0.3', 'OHM', '0.1'),
    ('Ohms', 'ohm', '600.0 Ω', 'OHM', '30', None, 'Ω', '30', '29.6', '30.4', 'OHM', '0.1'),
    ('Ohms', 'ohm', '600.0 Ω', 'OHM', '300', None, 'Ω', '300', '298.2', '301.8', 'OHM', '0.1'),
    ('Ohms', 'ohm', '600.0 Ω', 'OHM', '570', None, 'Ω', '570', '566.9', '573.1', 'OHM', '0.1'),
    ('Ohms', 'ohm', '6000 Ω', 'OHM', '900', None, 'Ω', '900', '894', '907', 'OHM', '1'),
    ('Ohms', 'ohm', '6000 Ω', 'OHM', '3000', None, 'Ω', '3000', '2982', '3018', 'OHM', '1'),
    ('Ohms', 'ohm', '6000 Ω', 'OHM', '5700', None, 'Ω', '5700', '5669', '5731', 'OHM', '1'),
    ('AC amps', 'aca', '200.0 A', 'ACI', '0.5', 50, 'A', '10', '9.6', '10.4', 'ACI50', '0.1'),
    ('AC amps', 'aca', '200.0 A', 'ACI', '5', 50, 'A', '100', '98.7', '101.3', 'ACI50', '0.1'),
    ('AC amps', 'aca', '200.0 A', 'ACI', '9.5', 50, 'A', '190', '187.5', '192.5', 'ACI50', '0.1'),
    ('AC amps', 'aca', '200.0 A', 'ACI', '0.5', 400, 'A', '10', '9.6', '10.4', 'ACI400', '0.1'),
    ('AC amps', 'aca', '200.0 A', 'ACI', '5', 400, 'A', '100', '98.5', '101.5', 'ACI400', '0.1'),
    ('AC amps', 'aca', '200.0 A', 'ACI', '9.5', 400, 'A', '190', '187.4', '192.6', 'ACI400', '0.1'),
    ('DC amps', 'dca', '200.0 A', 'DCI', '0.5', None, 'A', '10', '9.6', '10.4', 'DCI', '0.1'),
    ('DC amps', 'dca', '200.0 A', 'DCI', '5', None, 'A', '100', '98.7', '101.3', 'DCI', '0.1'),
    ('DC amps', 'dca', '200.0 A', 'DCI', '9.5', None, 'A', '190', '187.5', '192.5', 'DCI', '0.1'),
    ('DC amps', 'dca', '200.0 A', 'DCI', '-0.5', None, 'A', '-10', '-10.4', '-9.6', 'DCI', '0.1'),
    ('DC amps', 'dca', '200.0 A', 'DCI', '-5', None, 'A', '-100', '-101.3', '-98.7', 'DCI', '0.1'),
    ('DC amps', 'dca', '200.0 A', 'DCI', '-9.5', None, 'A', '-190', '-192.5', '-187.5', 'DCI', '0.1'),
]

COIL_TURNS = 20


def group_for(kind, applied):
    """Hook-up group: volts / ohms on the test leads; current through the coil on the calibrator's low-current (AUX) or high-current (20 A / 30 A) output
    (the 5522A AUX output reaches 2.999 A, the 5560A VI AUX 2.2 A: the 0.5 A points use it, 5 A and 9.5 A use the high-current terminal)."""
    if kind in ('ACI', 'DCI'):
        return 'COIL_AUX' if abs(D(applied)) < 3 else 'COIL_20A'
    return 'VOHM'


def fmt(d: D) -> str:
    return format(d, 'f')


def clean(value) -> float:
    return float(f'{float(value):.9g}')


def decimals(text: str) -> int:
    return max(0, -D(text).as_tuple().exponent)


def spec_halfwidth(nominal, acc, res):
    """Published specification at the reading `nominal`: +/-(% of reading + counts x resolution), in the display unit (Decimal)."""
    pct, counts = D(acc[0]), acc[1]
    return pct / 100 * abs(D(nominal)) + counts * D(res)


def check_row(step_no, nominal, low, high, acc, res):
    """Compare the printed limits with the published specification.  Returns (problems, info): problems are printed limits LOOSER than the full
    specification (the builder aborts); info is the list of disagreements with the half-width the manual's own pattern gives (flagged, not changed)."""
    full = spec_halfwidth(nominal, acc, res)
    half = full / 2
    nominal, low, high, res = D(nominal), D(low), D(high), D(res)
    problems, info = [], []
    for name, got in (('low', nominal - low), ('high', high - nominal)):
        if got > full + res / 2:
            problems.append(f'step {step_no}: the printed {name} limit is {got} from the nominal, LOOSER than the published specification {full}')
        elif abs(got - half) > res / 2:
            if nominal == 0 and name == 'low' and low == 0:
                continue                                                # ohms cannot read below zero: the lower limit 0 is the physical one
            info.append(dict(side=name, printed=fmt(got.normalize()), half_spec=fmt(half.normalize()), full_spec=fmt(full.normalize())))
    return problems, info


def build_steps():
    steps, problems, flagged = [], [], []
    for n, (section, sw, rng, kind, applied, freq, unit, nominal, low, high, acc_key, res) in enumerate(ROWS, 1):
        factor, base = UNITS[unit]
        acc = ACC[acc_key]
        p, info = check_row(f'{TABLE}-{n}', nominal, low, high, acc, res)
        problems += p
        low_f = fmt(D(low).quantize(D(res))) if decimals(low) < decimals(res) else low           # limits are written at the display resolution (same number)
        high_f = fmt(D(high).quantize(D(res))) if decimals(high) < decimals(res) else high
        assert D(low_f) == D(low) and D(high_f) == D(high), f'{TABLE}-{n}: reformatting changed a limit'
        step = dict(table=TABLE, step=n, section=section, switch=SW[sw], range=rng, models=[MODEL], kind=kind)
        coil = kind in ('ACI', 'DCI')
        a_value = clean(applied)
        step.update(display_unit=unit, factor=float(D(factor)), base_unit=base, low=low_f, high=high_f, test='numeric',
                    applied=dict(value=a_value, frequency=float(freq) if freq else None), nominal=clean(nominal))
        if (low_f, high_f) != (low, high):
            step['printed_text'] = dict(low=low, high=high, note='printed with fewer decimals than the display resolution; same value')
        pct, counts = acc
        word = f'{counts} digits of {res} {unit}'
        step['accuracy'] = f'±({pct} % of reading + {counts} digits)'
        full = spec_halfwidth(nominal, acc, res)
        step['tol_text'] = f'Table 2: {low_f} to {high_f} {unit}   (published specification: ±({pct} % of reading + {word}) = ±{fmt(full.normalize())} {unit}; the table keeps half of it)'
        notes = []
        if coil:
            notes.append(NOTE_COIL.format(applied=f'{D(applied).normalize():f}', nominal=f'{D(nominal).normalize():f}'))
            step['report_desc'] = f'{rng[:-2]} A, {D(applied).normalize():f} A x {COIL_TURNS} turns'          # short: the report's Description cell wraps beyond ~30 characters
            step['settle'] = 5
            # the line the technician sees for the point (handheld_dmm.describe reads dsb_desc when present; procmods_pointdef lists it as the point's description)
            step['dsb_desc'] = f'{section}, {COIL_TURNS}-turn coil, {rng} range: meter reads {D(nominal).normalize():f} A' + (f' @ {freq} Hz' if freq else '')
        if kind == 'OHM':
            notes.append(NOTE_OHMS + (' ' + NOTE_OHM_ZERO if D(applied) == 0 else ''))
        if info:
            sides = '; '.join(f'{i["side"]} limit ±{i["printed"]} vs half of the specification ±{i["half_spec"]}' for i in info)
            step['check'] = dict(printed_vs_spec=info, full_spec=fmt(full.normalize()))
            notes.append(f'CHECK (printed limit not changed): {sides} (full published specification ±{fmt(full.normalize())} {unit}; the printed limit is inside it).')
            flagged.append((f'{TABLE}-{n}', section, applied, freq, nominal, low, high, info))
        if sw == 'dca' and applied == '0.5':
            notes.append('Not in the Calibration Manual (UNVERIFIED): the meter has a ZERO button (Figure 1); with the jaw closed and nothing in it, a DC amps reading that is not zero may need it. '
                         'Do not zero with the coil in the jaw.')
        step['group'] = group_for(kind, applied)
        if notes:
            step['note'] = ' '.join(notes)
        step['ref'] = f'T{TABLE} #{n}'
        step['id'] = f'{TABLE}-{n}'
        steps.append(step)
    return steps, problems, flagged


GROUPS = {
    'COIL_AUX': dict(
        title='Change the cables: 20-turn coil on the calibrator low-current output',
        summary='Calibrator low-current output (5522A AUX HI / AUX LO; 5560A VI AUX / OUTPUT LO) -> 20-turn coil -> the meter jaw closed around all 20 turns. '
                'No test leads in the meter jacks.',
        steps=[
            ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
            ('Test leads', 'REMOVE the test leads from the VΩ and COM jacks: the manual says not to measure current while the test leads are in the input jacks (Safety Information, p. 2).'),
            ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
            ('Coil', 'The wired coil is 20 turns (Table 3, printed p. 8). Connect its two ends to the calibrator: Fluke 5522A AUX HI and AUX LO; Fluke 5560A VI AUX (HI) and OUTPUT LO. Use wire and plugs rated for the current.'),
            ('Jaw', 'Close the detachable jaw around ALL 20 turns of the coil together, jaw fully closed, the coil centred in the opening, the coil leads kept away from the meter body. The meter then reads 20 x the calibrator current. (The manual gives no jaw placement beyond "20 turn coil": UNVERIFIED.)'),
            ('LCOMP', 'Fluke 5522A: the program turns inductive-load compensation (LCOMP) ON for every AC point through the coil (read back with LCOMP?) and OFF afterwards (5522A Operators Manual p. 6-23; on the 5520A the command is UNVERIFIED). Where the calibrator does not allow it (440 Hz and above below 0.33 A; 1 kHz and above from 0.33 A) it is not set and the log says so. 5560A: no LCOMP command for its own output - set it yourself if needed.'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='This point drives current through a coil. Keep the calibrator in STANDBY whenever you touch the coil or leads. Do not exceed the jaw rating (600 V or 200 A, Safety Information p. 3).',
        diagram='diagrams/hook_fluke365_COIL_AUX.png'),
    'COIL_20A': dict(
        title='Change the cables: 20-turn coil on the calibrator high-current output',
        summary='Calibrator high-current output (5522A 20 A / AUX LO; 5560A 30A / OUTPUT LO) -> 20-turn coil -> the meter jaw closed around all 20 turns. '
                'No test leads in the meter jacks.',
        steps=[
            ('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
            ('Test leads', 'REMOVE the test leads from the VΩ and COM jacks: the manual says not to measure current while the test leads are in the input jacks (Safety Information, p. 2).'),
            ('Standby', 'The calibrator is put in STANDBY before you rewire (in manual-calibrator mode, put it in STANDBY yourself).'),
            ('Coil', 'Move the two ends of the 20-turn coil to the calibrator high-current terminals: Fluke 5522A 20 A and AUX LO; Fluke 5560A 30A and OUTPUT LO. The coil wire, plugs and leads must carry up to 9.5 A.'),
            ('Jaw', 'The detachable jaw stays closed around ALL 20 turns of the coil (centred, jaw fully closed, leads away from the meter body). The meter reads 20 x the calibrator current: 5 A reads 100 A, 9.5 A reads 190 A.'),
            ('LCOMP', 'Fluke 5522A: AC points through the coil - the program turns LCOMP ON for each (and OFF afterwards), as for the low-current points (the 20-turn coil: LCOMP ON for it is UNVERIFIED).'),
            ('Check', 'Compare your connections with the diagram, then continue.')],
        caution='Up to 9.5 A flows in the coil. Keep the calibrator in STANDBY whenever you touch the coil or leads; check that the coil and leads are not warm after a long run. '
                'Do not exceed the jaw rating (600 V or 200 A, Safety Information p. 3).',
        diagram='diagrams/hook_fluke365_COIL_20A.png'),
}

SOURCE_NOTE = (
    'Table 2 (32 rows: AC volts 6, DC volts 7, ohms 7, AC amps 6, DC amps 6; printed pp. 7-8 of the 365 Calibration Manual). The table has no step numbers: steps are numbered in '
    'table order. Table 3 (printed p. 8) names a calibrator with 4.5 digit resolution (Fluke 55xxA recommended) and a 20-turn wired coil; the procedure drives a Fluke 5522A or 5560A '
    '(or you set the calibrator by hand). The current rows are driven through the 20-turn coil: the calibrator output is 0.5 / 5 / 9.5 A and the meter reads 20 x that (limits are '
    'meter readings). The 365 has no remote interface: you type the display reading. Limits are as printed (nothing is corrected); where a printed limit is not half of the '
    'published specification (printed p. 5) the point says so: 900 ohm (lower limit 894, the pattern gives 893) and the three 190 A points (187.5 to 192.5, the pattern gives 187.8 to 192.2). '
    'High-voltage points go straight to the test value (the manual prescribes no ramp). Current points: test leads out of the jacks (p. 2), coil UNVERIFIED (turns wiring, jaw placement, '
    'calibrator compliance with the coil, 5522A LCOMP). The adjustment procedure (Tables 3 and 4, printed pp. 8-10) is not part of this procedure.')
REPORT_NOTE = (
    'Limits are those of the manufacturer\'s Table 2 (Fluke 365 Calibration Manual, printed pp. 7-8), unchanged. The current points are driven through a 20-turn coil '
    '(calibrator current x 20 = the reading shown). Their Uncertainty is the calibrator\'s current uncertainty at the actual output current (point / 20), unscaled and without the coil (owner-chosen convention); TAR / TUR compare it with the meter-reading tolerance.')


def build_spec():
    steps, problems, flagged = build_steps()
    if problems:
        raise SystemExit('The printed limits are looser than the published specification:\n  ' + '\n  '.join(problems))
    return dict(
        schema=3, kind='manual-reading',
        options=dict(hookup_meter='fluke365', hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, function_prompt=True, report_title='Calibration Data'),
        source=dict(document=DOCUMENT,
                    pages='5-8 (printed): specifications pp. 5-6, Table 2 pp. 7-8 (PDF pages 13-16); safety p. 2-3; Table 3 (equipment) p. 8',
                    cite='Fluke 365 Calibration Manual, Table 2 Performance Tests, printed pp. 7-8; limits unchanged, four rows flagged against the published specification (see Source)',
                    limits='Manufacturer limits, Table 2, as printed',
                    report_note=REPORT_NOTE, note=SOURCE_NOTE),
        models={MODEL: dict(name='Fluke 365', brand='Fluke', model_note='Fluke 365 detachable jaw true-rms clamp meter (200 A, 600 V, 4 digit display): Table 2, 32 points')},
        groups=GROUPS,
        steps=steps), flagged


def main():
    spec, flagged = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    count = {}
    for s in spec['steps']:
        count[s['section']] = count.get(s['section'], 0) + 1
    print('wrote', OUT, len(spec['steps']), 'steps;', count)
    for f in flagged:
        print('  FLAG', f[0], f[1], f'applied {f[2]}', f'{f[3]} Hz' if f[3] else 'dc', f'nominal {f[4]}', f'printed {f[5]} .. {f[6]}', f[7])


if __name__ == '__main__':
    main()
