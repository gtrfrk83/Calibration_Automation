"""Writes specs/keithley_2000_adjustment.json (Keithley Model 2000, guided comprehensive ADJUSTMENT over the remote :CAL:PROT commands).

Source: Keithley Model 2000 Multimeter Calibration Manual (2000-905-01 Rev. F, Aug 2007), read from RENDERED PAGE IMAGES (pdftoppm, 110 dpi pages, then a
170 / 220 dpi crop of Table 2-1 and Tables 2-8 to 2-10 read a second time), never from extracted text.  Printed pages used:
    2-2  introduction (comprehensive vs manufacturing calibration; "intended only for qualified service personnel")
    2-3  environment (23 C +/- 5 C, RH < 80 %), warm-up (at least one hour)
    2-4  calibration considerations (calibrator in operate, let the source settle, no scanner, 500 V peak common mode)
    2-5  calibration code (:CAL:PROT:CODE <up to 8 characters>; the manual prints the factory default: it is NOT stored anywhere in this suite)
    2-6  Table 2-1 recommended equipment (Fluke 5700A, Keithley 8610 low-thermal shorting plug); "Canceling calibration"
    2-7 .. 2-13  FRONT PANEL calibration (not built: the remote method below is used; Tables 2-3 to 2-7 were used to cross-check the remote tables)
    2-14 .. 2-19  SCPI COMMAND calibration (BUILT): preparing (p. 2-14), front-panel short and open (p. 2-15), Table 2-8 DC volts, Table 2-9 resistance (p. 2-16),
                  Table 2-10 DC current (p. 2-17), Table 2-11 AC volts, Table 2-12 AC current (pp. 2-18, 2-19), dates, save, lock (p. 2-19)
    2-20 .. 2-25  MANUFACTURING calibration (NOT built: OPEN key at power-up, 1 V 10 Hz / 3 Hz and a function generator / synthesizer; factory / repair only)
    3-4, 3-5  Table 3-1 command summary (note: STEP10 to STEP13 differ between firmware A19 and earlier and A20 and later)
    3-6 .. 3-9  :CODE :COUNt? :INIT :LOCK :LOCK? :SAVE :DATE :NDUE;  3-10 .. 3-17 DC / AC step commands;  3-19 error detection;  3-20 step completion (*OPC?)
    B-2, B-3  Table B-1 calibration error messages
    C-3 .. C-5  Appendix C BASIC program (the manual's own run order, used as a cross-check of the order and of the calibrator settings)

MANUAL MISPRINTS found while cross-reading (the value that agrees with the other tables is used; each is kept as a flag on the step and listed in the report):
    * Table 3-2 (p. 3-10) prints the 10 Mohm parameter limits as "9E-6 to 11E-6"; p. 3-14 (:STEP10) says 9E6 to 11E6, Table 2-9 (p. 2-16) says 9E6 to 11E6, Table 2-4 9 Mohm to 11 Mohm.
    * Table 3-3 (p. 3-16) and p. 3-17 label AC :STEP10 "100V AC at 1kHz"; Table 3-1 (p. 3-5), Table 2-6, Table 2-11 (p. 2-18) and Program C-1 all say 700 V at 1 kHz.
    * p. 3-17 labels AC :STEP11 "10mA AC"; Table 3-1, Table 2-7, Table 2-12 (p. 2-19) and Program C-1 say 100 mA at 1 kHz.
    * Appendix C Program C-1 uses the firmware A19 and earlier numbering (no 10 Mohm step, DC STEP10 = 10 mA): consistent with the note under Table 3-1.

Firmware: the DC steps after the 1 Mohm step are numbered differently on A19 and earlier ("do not have the 10 Megohm calibration step, and steps 10-12 are equivalent to
steps 11-13 in the A20 and later versions. There is no step 13", Table 3-1 note, p. 3-4).  Every step therefore carries `a20` (the number on A20 and later) and `a19`
(the number on A19 and earlier, None where the step does not exist); the program reads the revision from *IDN? (User Manual, common command *IDN?, PDF p. 122: "xxxxxxx, yyyyy/zzzzz",
yyyyy = digital board ROM revision) and the operator confirms it.

Run:  python specs/build_k2000_adjustment_spec.py
"""
import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'keithley_2000_adjustment.json'
DOC = 'Keithley Model 2000 Multimeter Calibration Manual (2000-905-01 Rev. F)'
UM = 'Keithley Model 2000 User Manual (2000-900 Rev. J)'

# ---- Table 2-1 (p. 2-6): the recommended equipment, ppm as printed (Fluke 5700A, 90-day, 23 C +/- 5 C specifications) ------------------------------------------
EQUIPMENT = {
    'calibrator': 'Fluke 5700A Calibrator (Table 2-1)',
    'shorting_plug': 'Keithley 8610 low-thermal shorting plug (Table 2-1, Figure 2-1)',
    'footnote': '*1 kHz specifications. 10 mV and 700 V points require 1 kHz only. All calibration specifications are 90-day, 23 C +/- 5 C specifications (Table 2-1 footnote).',
    'ppm': {   # function -> [(value text, unit, frequency text or '', +/- ppm as printed)]
        'DCV': [('10', 'V', '', 5), ('100', 'V', '', 7)],
        'ACV': [('10', 'mV', '1 kHz', 710), ('100', 'mV', '1 kHz, 50 kHz', 200), ('1', 'V', '1 kHz, 50 kHz', 82), ('10', 'V', '1 kHz, 50 kHz', 82),
                ('100', 'V', '1 kHz, 50 kHz', 90), ('700', 'V', '1 kHz', 85)],
        'DCI': [('10', 'mA', '', 60), ('100', 'mA', '', 70), ('1', 'A', '', 110)],
        'ACI': [('100', 'mA', '1 kHz', 190), ('1', 'A', '1 kHz', 690), ('2', 'A', '1 kHz', 670)],
        'OHM': [('1', 'kohm', '', 12), ('10', 'kohm', '', 11), ('100', 'kohm', '', 13), ('1', 'Mohm', '', 18), ('10', 'Mohm', '', 37)],
    },
}

GENERAL = [
    'This procedure changes the calibration constants of the Keithley Model 2000. The manual: "intended only for qualified service personnel" (p. 2-2). Complete the performance verification (As Found) first.',
    'Environment: 23 C +/- 5 C, relative humidity below 80 % (p. 2-3). Warm-up: at least ONE hour before calibration; allow the test equipment its own warm-up (p. 2-3); one extra hour if the unit was outside the stated temperature range.',
    'INPUTS switch on FRONT (button not pressed in) for every step (p. 2-15). The calibrator must be in OPERATE before each step, and the source signal must settle first (p. 2-4). No scanner or switching equipment between the calibrator and the 2000 (p. 2-4).',
    'Select the DC volts function and the SLOW rate (integration time 10 PLC) before starting (p. 2-14, step 3).',
    'Common-mode voltage (INPUT LO to chassis) must not exceed 500 V peak (p. 2-4 warning).',
    'Calibration constants are only TEMPORARY until :CAL:PROT:SAVE is sent (p. 2-19, p. 3-8). Nothing is stored before that command.',
]


def step(sid, scope, group, title, a20, a19, source=None, param=None, **extra):
    """One adjustment step. source: what the calibrator must output (None = no calibrator: short / open); param: the numeric parameter the command takes
    (nominal and the allowed range of the manual), None for a step with no parameter."""
    s = dict(id=sid, scope=scope, group=group, title=title, a20=a20, a19=a19, source=source, param=param)
    s.update(extra)
    return s


def src(kind, value, unit, freq=None):
    out = dict(kind=kind, value=str(value), unit=unit)
    if freq:
        out['frequency'] = str(freq)
    return out


def prm(nominal, lo, hi, unit):
    """The command parameter in base units (volts, ohms, amps): nominal and the allowed range as printed (Tables 2-8 to 2-10, p. 3-10 to 3-15)."""
    return dict(nominal=str(D(nominal)), lo=str(D(lo)), hi=str(D(hi)), unit=unit)


STEPS = [
    # ---- DC: front terminal short and open (pp. 2-15, 3-11) ----------------------------------------------------------------------------------------------------
    step('D01', 'DC', 'SHORT', 'Front terminal short circuit', 1, 1, page='2-15, 3-11', thermal_wait=True,
         note='Keithley 8610 low-thermal short on the front INPUT HI / LO and SENSE jacks (Figure 2-1); wait at least three minutes for thermal equilibrium before the command (p. 2-15).'),
    step('D02', 'DC', 'OPEN', 'Front terminal open circuit', 2, 2, page='2-15, 3-11',
         note='Remove the short; disconnect all cables and accessories from the front input jacks (p. 3-11).'),
    # ---- DC volts (Table 2-8, p. 2-16; p. 3-11, 3-12): calibrator external sense OFF ------------------------------------------------------------------------------
    step('D03', 'DC', 'DCV', '+10 V DC', 3, 3, src('DCV', 10, 'V'), prm('10', '9', '11', 'V'), page='2-16, 3-11', thermal_wait=True,
         note='Connect the calibrator (Figure 2-2) and wait three minutes for thermal equilibrium (p. 2-15); calibrator external sense OFF (p. 2-9).'),
    step('D04', 'DC', 'DCV', '-10 V DC', 4, 4, src('DCV', -10, 'V'), prm('-10', '-11', '-9', 'V'), page='2-16, 3-12'),
    step('D05', 'DC', 'DCV', '+100 V DC', 5, 5, src('DCV', 100, 'V'), prm('100', '90', '110', 'V'), page='2-16, 3-12', hv=True),
    # ---- resistance (Table 2-9, p. 2-16; pp. 3-12 to 3-14): 4-wire, calibrator external sense ON, the EXACT calibrator value is the parameter -----------------------------
    step('D06', 'DC', 'OHM4', '1 kohm 4-wire', 6, 6, src('OHM', 1000, 'ohm'), prm('1000', '900', '1100', 'ohm'), page='2-16, 3-12'),
    step('D07', 'DC', 'OHM4', '10 kohm 4-wire', 7, 7, src('OHM', 10000, 'ohm'), prm('10000', '9000', '11000', 'ohm'), page='2-16, 3-13'),
    step('D08', 'DC', 'OHM4', '100 kohm 4-wire', 8, 8, src('OHM', 100000, 'ohm'), prm('100000', '90000', '110000', 'ohm'), page='2-16, 3-13'),
    step('D09', 'DC', 'OHM4', '1 Mohm 4-wire', 9, 9, src('OHM', 1000000, 'ohm'), prm('1000000', '900000', '1100000', 'ohm'), page='2-16, 3-13',
         note='The 5522A cannot compensate (4-wire) above 110 kohm (ZCOMP, 5522A Operators Manual p. 6-49); how the sense leads are used at 1 Mohm is UNVERIFIED.'),
    step('D10', 'DC', 'OHM4', '10 Mohm', 10, None, src('OHM', 10000000, 'ohm'), prm('10000000', '9000000', '11000000', 'ohm'), page='2-16, 3-14',
         flags=['MISPRINT Table 3-2 (p. 3-10) prints the parameter limits as 9E-6 to 11E-6; p. 3-14 and Table 2-9 say 9E6 to 11E6 (used)',
                'FIRMWARE exists only on A20 and later (Table 3-1 note, p. 3-4)'],
         note='Firmware A20 and later only. Same unverified sense-lead remark as the 1 Mohm step.'),
    # ---- DC current (Table 2-10, p. 2-17; pp. 3-14, 3-15): calibrator output to AMPS / INPUT LO (Figure 2-3) ----------------------------------------------------------------
    step('D11', 'DC', 'DCI', '10 mA DC', 11, 10, src('DCI', '0.01', 'A'), prm('0.01', '0.009', '0.011', 'A'), page='2-17, 3-14',
         note='Connect the calibrator to the AMPS and INPUT LO jacks (Figure 2-3); calibrator set for normal current output.'),
    step('D12', 'DC', 'DCI', '100 mA DC', 12, 11, src('DCI', '0.1', 'A'), prm('0.1', '0.09', '0.11', 'A'), page='2-17, 3-14'),
    step('D13', 'DC', 'DCI', '1 A DC', 13, 12, src('DCI', 1, 'A'), prm('1', '0.9', '1.1', 'A'), page='2-17, 3-15'),
    # ---- AC volts (Table 2-11, p. 2-18; Table 3-3 / p. 3-17): no parameter; the stated voltage AND frequency must be used --------------------------------------------------
    step('A01', 'AC', 'ACV', '10 mV AC at 1 kHz', 1, 1, src('ACV', '0.01', 'V', 1000), page='2-18, 3-17'),
    step('A02', 'AC', 'ACV', '100 mV AC at 1 kHz', 2, 2, src('ACV', '0.1', 'V', 1000), page='2-18, 3-17'),
    step('A03', 'AC', 'ACV', '100 mV AC at 50 kHz', 3, 3, src('ACV', '0.1', 'V', 50000), page='2-18, 3-17'),
    step('A04', 'AC', 'ACV', '1 V AC at 1 kHz', 4, 4, src('ACV', 1, 'V', 1000), page='2-18, 3-17'),
    step('A05', 'AC', 'ACV', '1 V AC at 50 kHz', 5, 5, src('ACV', 1, 'V', 50000), page='2-18, 3-17'),
    step('A06', 'AC', 'ACV', '10 V AC at 1 kHz', 6, 6, src('ACV', 10, 'V', 1000), page='2-18, 3-17'),
    step('A07', 'AC', 'ACV', '10 V AC at 50 kHz', 7, 7, src('ACV', 10, 'V', 50000), page='2-18, 3-17'),
    step('A08', 'AC', 'ACV', '100 V AC at 1 kHz', 8, 8, src('ACV', 100, 'V', 1000), page='2-18, 3-17', hv=True),
    step('A09', 'AC', 'ACV', '100 V AC at 50 kHz', 9, 9, src('ACV', 100, 'V', 50000), page='2-18, 3-17', hv=True),
    step('A10', 'AC', 'ACV', '700 V AC at 1 kHz', 10, 10, src('ACV', 700, 'V', 1000), page='2-18, 3-5, 3-17', hv=True,
         flags=['MISPRINT Table 3-3 (p. 3-16) and p. 3-17 label this step "100V AC at 1kHz"; Table 3-1, Table 2-6, Table 2-11 and Program C-1 say 700 V at 1 kHz (used)']),
    # ---- AC current (Table 2-12, p. 2-19): calibrator output to AMPS / INPUT LO (Figure 2-3) --------------------------------------------------------------------------------
    step('A11', 'AC', 'ACI', '100 mA AC at 1 kHz', 11, 11, src('ACI', '0.1', 'A', 1000), page='2-19, 3-17',
         flags=['MISPRINT p. 3-17 labels this step "10mA AC"; Table 3-1, Table 2-7, Table 2-12 and Program C-1 say 100 mA at 1 kHz (used)']),
    step('A12', 'AC', 'ACI', '1 A AC at 1 kHz', 12, 12, src('ACI', 1, 'A', 1000), page='2-19, 3-17'),
    step('A13', 'AC', 'ACI', '2 A AC at 1 kHz', 13, 13, src('ACI', 2, 'A', 1000), page='2-19, 3-17'),
]

FIRMWARE = {
    'note': 'Table 3-1 note, p. 3-4: STEP10 to STEP13 differ between firmware A19 and A20. A19 and earlier have no 10 Mohm step; their steps 10-12 are the 10 mA, 100 mA and 1 A steps '
            '(A20 and later: 11-13); there is no step 13 on A19 and earlier. AC steps are the same on both.',
    'idn': UM + ' (common command *IDN?, PDF p. 122): *IDN?: KEITHLEY INSTRUMENTS INC., MODEL 2000, xxxxxxx, yyyyy/zzzzz (yyyyy = firmware revision of the digital board ROM, zzzzz = display board ROM); the revision text format (e.g. A19) is UNVERIFIED on a real meter.',
    'boundary': 'A20',
}

REMOTE_SEQUENCE = [
    ('prepare', 'DCV function, SLOW rate (10 PLC), INPUTS front (p. 2-14 steps 3-4)'),
    ('code', ':CAL:PROT:CODE <code> sent ONCE (p. 2-14 step 5; p. 3-6: "sent only once ... Do not send :CODE before each calibration step")'),
    ('init', ':CAL:PROT:INIT sent ONCE (p. 2-14 step 6; p. 3-7)'),
    ('steps', 'DC then AC steps in the order of Tables 2-8 to 2-12 (a complete calibration; DC only or AC only are allowed, p. 2-14 note); wait for each step to finish (p. 3-20, *OPC?)'),
    ('dates', ':CAL:PROT:DATE and :CAL:PROT:NDUE (p. 2-19); errors +438 / +439 if they are not set (Table B-1)'),
    ('save', ':CAL:PROT:SAVE (p. 2-19, p. 3-8): stores the constants in EEROM; "only temporary unless :SAVE is sent"'),
    ('lock', ':CAL:PROT:LOCK (p. 2-19, p. 3-7); :CAL:PROT:LOCK? 0 = locked, 1 = unlocked'),
]

# Table B-1 (pp. B-2, B-3): errors that can occur during calibration (number -> text as printed)
ERRORS = {
    400: '10 vdc zero error', 401: '100 vdc zero error', 402: '10 vdc full scale error', 403: '-10 vdc full scale error', 404: '100 vdc full scale error', 405: '-100 vdc full scale error',
    406: '1k 2-w zero error', 407: '10k 2-w zero error', 408: '100k 2-w zero error', 409: '10M 2-w zero error', 410: '10M 2-w full scale error', 411: '10M 2-w open error',
    412: '1k 4-w zero error', 413: '10k 4-w zero error', 414: '100k 4-w zero error', 415: '10M 4-w sense lo zero error', 416: '1k 4-w full scale error', 417: '10k 4-w full scale error',
    418: '100k 4-w full scale error', 419: '1M 4-w full scale error', 420: '10M 4-w full scale error', 421: '10m adc zero error', 422: '100m adc zero error', 423: '10m adc full scale error',
    424: '100m adc full scale error', 425: '1 adc full scale error', 438: 'Date of calibration not set', 439: 'Next date of calibration not set',
    450: '100m vac dac error', 451: '1 vac dac error', 452: '10 vac dac error', 453: '100 vac dac error', 454: '100m vac zero error', 455: '100m vac full scale error',
    456: '1 vac zero error', 457: '1 vac full scale error', 458: '1 vac noise error', 459: '10 vac zero error', 460: '10 vac full scale error', 461: '10 vac noise error',
    462: '100 vac zero error', 463: '100 vac full scale error', 464: '750 vac zero error', 465: '750 vac full scale error', 466: '750 vac noise error', 467: 'Post filter offset error',
    468: '1 aac zero error', 469: '1 aac full scale error', 470: '3 aac zero error', 471: '3 aac full scale error', 472: 'Input time constant error', 473: 'Frequency gain error',
    499: '1V, 10Hz frequency error', 500: 'Calibration data invalid', 513: 'AC calibration data lost', 514: 'DC calibration data lost', 515: 'Calibration dates lost', 610: 'Questionable Calibration',
}


def check(steps):
    """Self-checks: unique ids, A20 numbers 1-13 each once per scope, A19 numbers consistent with the p. 3-4 note, parameter nominal inside its range."""
    ids = [s['id'] for s in steps]
    assert len(ids) == len(set(ids)), 'duplicate step id'
    dc = {s['a20']: s for s in steps if s['scope'] == 'DC'}
    ac = {s['a20']: s for s in steps if s['scope'] == 'AC'}
    assert sorted(dc) == list(range(1, 14)), sorted(dc)
    assert sorted(ac) == list(range(1, 14)), sorted(ac)
    for n, s in dc.items():
        want = n if n <= 9 else None if n == 10 else n - 1                      # p. 3-4: A19 steps 10-12 are A20's 11-13, no 10 Mohm step, no step 13
        assert s['a19'] == want, (s['id'], s['a19'], want)
    for s in steps:
        p = s['param']
        if p:
            assert D(p['lo']) <= D(p['nominal']) <= D(p['hi']), s['id']
            assert s['source'] is not None
        if s['scope'] == 'AC':
            assert p is None and s['a19'] == s['a20'], s['id']


def main():
    check(STEPS)
    doc = dict(schema=1, kind='bench-dmm-adjustment', instrument='Keithley Model 2000', source=DOC, method='remote :CAL:PROT commands (SCPI command calibration, pp. 2-14 to 2-19)',
               general=GENERAL, equipment=EQUIPMENT, firmware=FIRMWARE, sequence=[dict(id=a, text=b) for a, b in REMOTE_SEQUENCE], steps=STEPS,
               errors={str(k): v for k, v in ERRORS.items()},
               not_built=['Manufacturing calibration (:CAL:PROT:DC:STEP0, AC:STEP14, AC:STEP15; OPEN key at power-up; function generator / synthesizer): factory or repair only (pp. 2-20 to 2-25)',
                          'Front panel (keystroke) calibration: the remote method is provided by the manual and is used instead (pp. 2-7 to 2-13)'],
               times=dict(thermal_wait_s=180, nplc_slow=10, date_years=1))
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=True) + '\n', encoding='utf-8')
    print(f'wrote {OUT.name}: {len(STEPS)} steps ({sum(1 for s in STEPS if s["scope"] == "DC")} DC, {sum(1 for s in STEPS if s["scope"] == "AC")} AC)')


if __name__ == '__main__':
    main()
