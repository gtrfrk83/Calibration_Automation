"""Builds specs/fluke_287_289_pv.json for the shared handheld engine (handheld_dmm.py): Fluke 287 and 289 performance tests.

Source: Fluke 287/289 True-rms Digital Multimeters Calibration Manual, Performance Tests, pp. 14-20 (printed): functional checks
pp. 15-16, Table 3 Temperature (p. 17), Table 4 Performance Test Steps (pp. 17-20) with its footnotes. Every limit below was read from
the rendered page images, not from extracted text, and is kept exactly as printed (strings, so the comparison is exact).

What the table does not say and is added here (shown to the technician):
  * the calibrator output kind and wiring group, and which steps the program cannot source (kind NONE - set by hand):
    step 25 (0.707 V p-p, 950 kHz, 50 ohm: 5520A scope option LEVSINE, footnote 8), step 29 (5 V p-p square, 15 % duty, 50 kHz),
    step 41 (4 V p-p square, +1 V offset, 2 kHz);
  * the IR check for each point ('ir'): which reading unit to take from the display, the range the table names, and the REL and
    Low Pass state the step requires. Ranges the remote spec cannot express (400 mA, diode 3.1 V) are not range-checked.
REL handling (the table's grey "REL Offset" rows): step 1 ("allow reading to stabilize", 0 mV) is folded into step 2, which applies
0 mV, has you press REL once the reading is stable, then records the reading; steps 11 and 46 do the same at 0 ohm (rel_zero);
step 42 zeroes with the leads removed (footnote 4). "Discontinue REL" rows become a prompt on the next step.
Step 45 ("allow reading to stabilize", no limits) is the REL zero of step 46.

    python specs/build_28x_spec.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_287_289_pv.json'
BOTH, ONLY289 = ['287', '289'], ['289']

UNITS = {   # display unit -> (factor to base unit, base unit, IR unit for DC / AC)
    'mV': (0.001, 'V'), 'V': (1.0, 'V'), 'Ω': (1.0, 'ohm'), 'kΩ': (1e3, 'ohm'), 'MΩ': (1e6, 'ohm'), 'Hz': (1.0, 'Hz'),
    'kHz': (1e3, 'Hz'), '%': (1.0, '%'), 'nF': (1e-9, 'F'), 'µA': (1e-6, 'A'), 'mA': (1e-3, 'A'), 'A': (1.0, 'A'), '°C': (1.0, 'C')}
RANGE_CODE = {'50.000 mV': (50, -3), '500.00 mV': (500, -3), '500.00 Ω': (500, 0), '5.0000 kΩ': (5, 3), '50.000 kΩ': (50, 3),
              '500.00 kΩ': (500, 3), '5.0000 MΩ': (5, 6), '30.000 MΩ': (30, 6), '500.0 MΩ': (500, 6), '5.0000 V': (5, 0),
              '5.000 V': (5, 0), '50.000 V': (50, 0), '500.00 V': (500, 0), '1000.0 V': (1000, 0), '1000 V': (1000, 0), '10.00 nF': (10, -9),
              '500.00 µA': (500, -6), '5000.0 µA': (5000, -6), '50.000 mA': (50, -3), '5.0000 A': (5, 0), '10.000 A': (10, 0),
              '50.000 Ω': (50, 0)}
SWITCH = {'DCMV': 'mV ⎓ / temperature position (DC millivolts)', 'ACMV': 'mV ~ position (AC millivolts)',
          'ACV': 'V ~ position (AC volts)', 'DCV': 'V ⎓ position (DC volts)', 'OHM': 'Ω position (ohms)',
          'CAP': 'Ω position, capacitance (press the yellow button)', 'DIODE': 'diode / continuity position',
          'LOOHM': 'Ω position, LoΩ (289)', 'UA': 'µA position (current)', 'MA': 'mA / A position, mA', 'A': 'mA / A position, A',
          'LOZ': 'LoZ position (289)', 'TEMP': 'mV ⎓ / temperature position, temperature (°C)'}

steps = []


def add(step, section, sw, rng, kind, applied, unit, low, high, freq=None, models=BOTH, group=None, ir=None, **extra):
    factor, base = UNITS[unit]
    nominal = extra.pop('nominal', None)
    if nominal is None:
        nominal = applied
    p = dict(table='4', step=step, id=f'4-{step}', section=section, switch=SWITCH[sw], range=rng, models=models, kind=kind,
             display_unit=unit, factor=factor, base_unit=base, low=low, high=high, test='numeric',
             nominal=nominal)
    if kind != 'NONE':
        p['applied'] = dict(value=applied, frequency=freq)
    if group:
        p['group'] = group
    if ir is not None:
        if rng in RANGE_CODE and 'range' not in ir:
            ir['range'] = list(RANGE_CODE[rng])
        ir.setdefault('rel', False)
        p['ir'] = ir
    p.update(extra)
    steps.append(p)


DCV, ACV, OHM, ADC, AAC = 'VDC', 'VAC', 'OHM', 'ADC', 'AAC'
REL_ZERO_NOTE = 'Thermal offsets (manual note): after connecting, allow time - it can be several minutes - for the reading to settle before REL.'

# ---- DC mV (p. 17-18) ---------------------------------------------------------------------------------------------------------------
add(2, 'DC mV', 'DCMV', '50.000 mV', 'DCV', 0.0, 'mV', '-0.020', '0.020', ir=dict(unit=DCV, rel=True),
    rel_zero=dict(value=0.0, text='0 mV is applied (manual step 1). When the reading is stable, press REL (Δ). ' + REL_ZERO_NOTE),
    ref='T4 #1-2')
add(3, 'DC mV', 'DCMV', '50.000 mV', 'DCV', 0.025e-3, 'mV', '0.005', '0.045', ir=dict(unit=DCV, rel=True))
add(4, 'DC mV', 'DCMV', '50.000 mV', 'DCV', -0.025e-3, 'mV', '-0.045', '-0.005', ir=dict(unit=DCV, rel=True))
add(5, 'DC mV', 'DCMV', '50.000 mV', 'DCV', 50e-3, 'mV', '49.955', '50.045', ir=dict(unit=DCV, rel=True))
add(6, 'DC mV', 'DCMV', '500.00 mV', 'DCV', 0.5, 'mV', '499.85', '500.15', ir=dict(unit=DCV),
    prompt='Discontinue REL: press REL so that REL (Δ) is no longer shown, then select the 500 mV range.')
add(7, 'DC mV', 'DCMV', '500.00 mV', 'DCV', -0.25, 'mV', '-250.08', '-249.92', ir=dict(unit=DCV))
add(8, 'DC mV, DC/AC', 'DCMV', '500.00 mV', 'DCV', 50e-3, 'mV', '49.97', '50.03', ir=dict(unit=DCV),
    note='Select the DC/AC display (DC reading in the primary display, AC in the secondary). Input: 50 mV DC (0 Hz).')
add(9, 'DC mV, AC/DC', 'DCMV', '500.00 mV', 'ACV', 0.25, 'mV', '237.10', '262.90', freq=35e3, ir=dict(unit=ACV),
    note='Select the AC/DC display (AC reading in the primary display). Input: 250 mV at 35 kHz.')

# ---- Ohms (p. 18): 2-wire COMP, 4-wire connection for steps 10-14 -------------------------------------------------------------------
add(10, 'Ohms', 'OHM', '500.00 Ω', 'OHM', 0.0, 'Ω', '-0.10', '0.10', group='OHM4', ir=dict(unit=OHM))
add(11, 'Ohms', 'OHM', '500.00 Ω', 'OHM', 0.2, 'Ω', '0.10', '0.30', group='OHM4', ir=dict(unit=OHM, rel=True),
    rel_zero=dict(value=0.0, text='0 Ω is applied. When the reading is stable, press REL (Δ).'))
add(12, 'Ohms', 'OHM', '500.00 Ω', 'OHM', 500.0, 'Ω', '499.65', '500.35', group='OHM4', ir=dict(unit=OHM, rel=True))
add(13, 'Ohms', 'OHM', '5.0000 kΩ', 'OHM', 5e3, 'kΩ', '4.9973', '5.0027', group='OHM4', ir=dict(unit=OHM),
    prompt='Discontinue REL: press REL so that REL (Δ) is no longer shown.')
add(14, 'Ohms', 'OHM', '50.000 kΩ', 'OHM', 50e3, 'kΩ', '49.973', '50.027', group='OHM4', ir=dict(unit=OHM))
add(15, 'Ohms', 'OHM', '500.00 kΩ', 'OHM', 500e3, 'kΩ', '499.73', '500.27', ir=dict(unit=OHM))
add(16, 'Ohms', 'OHM', '5.0000 MΩ', 'OHM', 5e6, 'MΩ', '4.9921', '5.0079', ir=dict(unit=OHM))
add(17, 'Ohms', 'OHM', '30.000 MΩ', 'OHM', 30e6, 'MΩ', '29.546', '30.454', ir=dict(unit=OHM))
add(18, 'Ohms', 'OHM', '500.0 MΩ', 'OHM', 300e6, 'MΩ', '275.8', '324.2', ir=dict(unit=OHM), settle=10)

# ---- AC mV and frequency (p. 18) ------------------------------------------------------------------------------------------------------
add(19, 'AC mV', 'ACMV', '50.000 mV', 'ACV', 5e-3, 'mV', '4.865', '5.135', freq=20, ir=dict(unit=ACV))
add(20, 'AC mV', 'ACMV', '50.000 mV', 'ACV', 50e-3, 'mV', '48.210', '51.790', freq=65e3, ir=dict(unit=ACV))
add(21, 'AC mV', 'ACMV', '500.00 mV', 'ACV', 50e-3, 'mV', '47.85', '52.15', freq=100e3, ir=dict(unit=ACV))
add(22, 'AC mV', 'ACMV', '500.00 mV', 'ACV', 0.25, 'mV', '240.85', '259.15', freq=65e3, ir=dict(unit=ACV))
add(23, 'AC mV', 'ACMV', '500.00 mV', 'ACV', 0.5, 'mV', '498.25', '501.75', freq=45, ir=dict(unit=ACV))
add(24, 'AC mV, Hz', 'ACMV', '500.00 mV', 'ACV', 0.5, 'Hz', '44.986', '45.014', freq=45, nominal=45.0, ir=dict(unit='Hz'),
    note='Press Hz: the frequency reading is recorded.')
add(25, 'AC mV, Hz', 'ACMV', '500.00 mV', 'NONE', None, 'kHz', '949.90', '950.10', nominal=950e3, ir=dict(unit='Hz'),
    setup='Set the calibrator by hand: 0.707 V p-p sine at 950 kHz from a 50 Ω output (5520A scope option: LEVSINE mode, manual '
          'footnote 8) to the meter V and COM inputs, and press OPERATE. Meter: AC mV, 500 mV range, Hz. Put the calibrator in '
          'STANDBY after the reading.', note='Press Hz: the frequency reading is recorded.')

# ---- AC volts (pp. 18-19) --------------------------------------------------------------------------------------------------------------
add(26, 'AC volts', 'ACV', '5.0000 V', 'ACV', 0.1, 'V', '0.0952', '0.1048', freq=60, ir=dict(unit=ACV, lowpass=False))
add(27, 'AC volts', 'ACV', '5.0000 V', 'ACV', 0.5, 'V', '0.4945', '0.5055', freq=10e3, ir=dict(unit=ACV, lowpass=False))
add(28, 'AC volts', 'ACV', '5.0000 V', 'ACV', 3.0, 'V', '2.8160', '3.1840', freq=100e3, ir=dict(unit=ACV, lowpass=False))
add(29, 'AC volts, Hz, % duty cycle', 'ACV', '5.0000 V', 'NONE', None, '%', '1.40', '28.60', nominal=15.0, ir=dict(unit='PCT'),
    setup='Set the calibrator by hand: 5 V p-p square wave, 15 % duty cycle, 50 kHz, to the meter V and COM inputs, and press OPERATE. '
          'Meter: AC V, 5 V range, press Hz until % (duty cycle) is shown. Put the calibrator in STANDBY after the reading.')
add(30, 'AC volts', 'ACV', '50.000 V', 'ACV', 15.0, 'V', '14.435', '15.565', freq=100e3, ir=dict(unit=ACV, lowpass=False))
add(31, 'AC volts, Low Pass', 'ACV', '500.00 V', 'ACV', 50.0, 'V', '48.60', '51.40', freq=60, models=ONLY289,
    ir=dict(unit=ACV, lowpass=True), prompt='Turn the Low Pass filter ON (289).')
add(32, 'AC volts, Low Pass', 'ACV', '500.00 V', 'ACV', 50.0, 'V', '0.00', '8.00', freq=1600, models=ONLY289, nominal=50.0,
    ir=dict(unit=ACV, lowpass=True), note='Footnote 3: accuracy is not specified at 1600 Hz with the Low Pass filter on; the limits check '
                                         'that the filter is active and follows the expected roll-off.')
add(33, 'AC volts', 'ACV', '500.00 V', 'ACV', 500.0, 'V', '497.75', '502.25', freq=10e3, ir=dict(unit=ACV, lowpass=False),
    prompt='289: turn the Low Pass filter OFF.')
add(34, 'AC volts', 'ACV', '1000.0 V', 'ACV', 1000.0, 'V', '993.5', '1006.5', freq=10e3, ir=dict(unit=ACV, lowpass=False))

# ---- DC volts (p. 19) -------------------------------------------------------------------------------------------------------------------
add(35, 'DC volts', 'DCV', '5.0000 V', 'DCV', 4.0, 'V', '3.9988', '4.0012', ir=dict(unit=DCV))
add(36, 'DC volts', 'DCV', '50.000 V', 'DCV', -40.0, 'V', '-40.012', '-39.988', ir=dict(unit=DCV))
add(37, 'DC volts', 'DCV', '500.00 V', 'DCV', 400.0, 'V', '399.86', '400.14', ir=dict(unit=DCV))
add(38, 'DC volts', 'DCV', '1000.0 V', 'DCV', 600.0, 'V', '599.6', '600.4', ir=dict(unit=DCV))
add(39, 'DC volts, DC/AC', 'DCV', '5.0000 V', 'DCV', 0.2, 'V', '0.1977', '0.2023', ir=dict(unit=DCV),
    note='Select the DC/AC display (DC reading in the primary display). Input: 200 mV DC (0 Hz).')
add(40, 'DC volts, AC/DC', 'DCV', '5.0000 V', 'ACV', 2.0, 'V', '1.9640', '2.0360', freq=5e3, ir=dict(unit=ACV),
    note='Select the AC/DC display (AC reading in the primary display). Input: 2 V at 5 kHz.')
add(41, 'AC volts, Peak', 'ACV', '5.000 V', 'NONE', None, 'V', '1.863', '2.137', nominal=2.0, ir=dict(unit=ACV),
    setup='Set the calibrator by hand: 4 V p-p square wave with a +1 V DC offset at 2 kHz, to the meter V and COM inputs, and press '
          'OPERATE. Meter: AC V, 5 V range, Peak. Put the calibrator in STANDBY after the reading.')

# ---- Capacitance and diode (p. 19) -------------------------------------------------------------------------------------------------------
add(42, 'Capacitance', 'CAP', '10.00 nF', 'CAP', 5e-9, 'nF', '4.90', '5.10', ir=dict(unit='F', rel=True, functions=['CAPACITANCE']),
    rel_zero=dict(value=None, text='Turn the rotary switch to capacitance and select the 10 nF range. Remove the test leads from the '
                                   'calibrator (leave them in the meter), press REL (Δ), then reconnect the leads to the calibrator.'),
    note='Footnote 4: with a film capacitor or better, using relative mode (REL) to zero the residual.')
add(43, 'Diode test', 'DIODE', '3.1000 V', 'OHM', 3.5e3, 'V', '2.0000', '3.1000', ir=dict(unit=DCV, functions=['DIODE_TEST']),
    nominal=2.55, no_uncertainty=True, prompt='Diode test: if REL (Δ) is still shown from the capacitance step, press REL to turn it off.',
    note='Input 3.5 kΩ; the table prints no nominal, so the report shows the mid-limit 2.55 V.')
steps.append(dict(table='4', step=44, id='4-44', section='Diode test', switch=SWITCH['DIODE'], range='3.1000 V', models=BOTH, kind='OHM',
                  test='beeper', expect='on', applied=dict(value=0.0, frequency=None), nominal=0.0, base_unit='ohm', display_unit='Ω',
                  factor=1.0, question='The beeper is ON (sounding).'))

# ---- LoΩ (289, p. 19): 2-wire COMP, 4-wire connection ----------------------------------------------------------------------------------
add(46, 'LoΩ', 'LOOHM', '50.000 Ω', 'OHM', 0.2, 'Ω', '0.180', '0.220', models=ONLY289, group='OHM4',
    ir=dict(unit=OHM, rel=True, functions=['OHMS_LOW']), ref='T4 #45-46',
    rel_zero=dict(value=0.0, text='0 Ω is applied (manual step 45). Allow the reading to stabilize (5-10 seconds), then press REL (Δ).'))
add(47, 'LoΩ', 'LOOHM', '50.000 Ω', 'OHM', 50.0, 'Ω', '49.905', '50.095', models=ONLY289, group='OHM4',
    ir=dict(unit=OHM, rel=True, functions=['OHMS_LOW']))

# ---- µA / mA (p. 20) ----------------------------------------------------------------------------------------------------------------------
G5 = 'Footnote 5: limit mathematically guard banded to ensure performance at 20 kHz and lower.'
add(48, 'µA AC', 'UA', '500.00 µA', 'ACI', 500e-6, 'µA', '496.80', '503.20', freq=60, group='UAMP', ir=dict(unit=AAC))
add(49, 'µA AC', 'UA', '500.00 µA', 'ACI', 500e-6, 'µA', '492.85', '507.15', freq=30e3, group='UAMP', ir=dict(unit=AAC), note=G5)
add(50, 'µA AC', 'UA', '5000.0 µA', 'ACI', 5000e-6, 'µA', '4928.5', '5071.5', freq=30e3, group='UAMP', ir=dict(unit=AAC), note=G5)
add(51, 'µA DC', 'UA', '500.00 µA', 'DCI', 500e-6, 'µA', '499.42', '500.58', group='UAMP', ir=dict(unit=ADC))
add(52, 'µA DC', 'UA', '5000.0 µA', 'DCI', 5000e-6, 'µA', '4996.0', '5004.0', group='UAMP', ir=dict(unit=ADC))
add(53, 'mA AC', 'MA', '50.000 mA', 'ACI', 4e-3, 'mA', '3.940', '4.060', freq=20, group='UAMP', ir=dict(unit=AAC))
add(54, 'mA AC', 'MA', '50.000 mA', 'ACI', 30e-3, 'mA', '29.375', '30.625', freq=30e3, group='UAMP', ir=dict(unit=AAC), note=G5)
add(55, 'mA AC', 'MA', '400.00 mA', 'ACI', 0.3, 'mA', '284.60', '315.40', freq=30e3, group='UAMP', ir=dict(unit=AAC))
add(56, 'mA AC', 'MA', '400.00 mA', 'ACI', 0.4, 'mA', '397.55', '402.45', freq=60, group='UAMP', ir=dict(unit=AAC))
add(57, 'mA DC', 'MA', '50.000 mA', 'DCI', 0.1e-3, 'mA', '0.090', '0.110', group='UAMP', ir=dict(unit=ADC))
add(58, 'mA DC', 'MA', '50.000 mA', 'DCI', 50e-3, 'mA', '49.965', '50.035', group='UAMP', ir=dict(unit=ADC))
add(59, 'mA DC', 'MA', '400.00 mA', 'DCI', 0.4, 'mA', '399.38', '400.62', group='UAMP', ir=dict(unit=ADC))

# ---- A (p. 20) -----------------------------------------------------------------------------------------------------------------------------
add(60, 'A AC', 'A', '5.0000 A', 'ACI', 5.0, 'A', '4.9580', '5.0420', freq=1e3, group='AMP10', ir=dict(unit=AAC), settle=5)
add(61, 'A AC', 'A', '10.000 A', 'ACI', 5.0, 'A', '4.955', '5.045', freq=1e3, group='AMP10', ir=dict(unit=AAC), settle=5)
add(62, 'A DC', 'A', '5.0000 A', 'DCI', 5.0, 'A', '4.9840', '5.0160', group='AMP10', ir=dict(unit=ADC), settle=5)
add(63, 'A DC', 'A', '10.000 A', 'DCI', 10.0, 'A', '9.968', '10.032', group='AMP10', ir=dict(unit=ADC), settle=5)

# ---- LoZ (289, p. 20): 120 V reached through 60 V (footnote 7) --------------------------------------------------------------------------
add(64, 'LoZ', 'LOZ', '1000 V', 'ACV', 120.0, 'V', '113.6', '126.4', freq=60, models=ONLY289, ir=dict(unit=ACV, functions=['V_AC_LOZ']),
    ramp=[60.0, 120.0], note='Footnote 7: the calibrator is stepped to 60 V, then 120 V, to avoid an overload / current limit. '
                             'Footnote 6: let the meter stabilize 20 minutes after LoZ before any DC mV, temperature, ohms or LoΩ test.')

# ---- Table 3: temperature (p. 17) ------------------------------------------------------------------------------------------------------------
TEMP_SETUP = ('On the meter: mV ⎓ / temperature position, temperature, °C; select Offset and set it to 000.0, then close the Offset window. '
              'K-type thermocouple (mini-plug both ends) from the calibrator TC output to the Fluke 80AK in the meter V and COM inputs. '
              'The meter must be within ±1 °C of ambient (can take hours); allow the connections 2 minutes to stabilize.')
for n, (t, lo, hi) in enumerate(((0.0, '-1.0', '1.0'), (100.0, '98.0', '102.0'), (1000.0, '989.0', '1011.0')), 1):
    steps.append(dict(table='3', step=n, id=f'3-{n}', section='Temperature', switch=SWITCH['TEMP'], range='', models=BOTH, kind='TEMP',
                      display_unit='°C', factor=1.0, base_unit='C', low=lo, high=hi, test='numeric', applied=dict(value=t, frequency=None),
                      nominal=t, group='TEMP', settle=120 if n == 1 else 20, ir=dict(unit='CEL', offset_zero=True)))

# ---- functional checks (pp. 15-16) -------------------------------------------------------------------------------------------------------------
F = [('Factory default', 'Power the meter on, press F4 (Setup), select Reset with the arrow keys, press F3 (Meter), then F1 (OK).',
      'The meter was reset to factory defaults and went through its power-up routine.'),
     ('Power LED', 'Power the meter on.', 'The power button lights for about 4 seconds, then goes out.'),
     ('Backlight', 'Press the backlight button twice.', 'The backlight comes on at two different intensity levels.'),
     ('Current terminal sensing (Input Alert)', 'The beeper must be enabled in Setup. Put a test lead in the mA/µA terminal and turn the rotary '
      'switch through all functions except current, then to A/mA. Repeat with the lead in the A terminal.',
      'With the lead in mA/µA and then in A: the beeper chirps and a warning is shown in every non-current function, and not in A/mA.'),
     ('Keypad', 'The beeper must be enabled in Setup. Press each button once.', 'Every button press beeps.'),
     ('LCD', 'Turn the switch to mV ⎓ and the meter on. F4 Setup > Contrast: backlight to maximum, F1/F2 for the brightest display. Press "i Info" '
      'and scroll the text with F1 and F2.', 'No missing pixels or unreadable areas.'),
     ('IR port', 'Connect the IR cable to the meter IR port and a PC (115200 baud, 8 N 1) and send ID.',
      'The meter answers FLUKE 287 or FLUKE 289 with its software version and serial number.')]
for n, (title, setup, q) in enumerate(F, 1):
    s = dict(table='F', step=n, id=f'F-{n}', section='Functional checks', switch=title, range='', models=BOTH, kind='VISUAL', test='visual',
             title=title, setup=setup, question=q)
    if title == 'IR port':
        s['ir_auto'] = 'id'
        s['note'] = 'With "Read over IR" selected this check is done automatically (the meter must answer ID with its model).'
    steps.append(s)

GROUPS = {
    'VOHM': dict(title='Connect for voltage, resistance (2-wire) and capacitance',
                 summary='Calibrator NORMAL HI / LO (5560A: OUTPUT V/Ω) to the meter V and COM inputs.',
                 steps=[['Standby', 'The calibrator is in STANDBY while you rewire.'],
                        ['Connect', 'Calibrator NORMAL HI / LO (5560A: OUTPUT V/Ω HI / LO) to the meter V (red) and COM (black) inputs.'],
                        ['Calibrator', 'Ohms compensation OFF (COMP off) and the auxiliary cable removed (manual, before step 15).']]),
    'OHM4': dict(title='Ohms: 2-wire COMP, 4-wire connection',
                 summary='Calibrator 2-wire COMP; NORMAL HI/LO and AUX HI/LO (sense) leads to the meter V and COM inputs.',
                 steps=[['Standby', 'The calibrator is in STANDBY while you rewire.'],
                        ['Calibrator', 'Set ohms compensation to 2-wire COMP on the calibrator front panel (the program does not set it).'],
                        ['Connect', 'Connect in the 4-wire configuration: NORMAL HI and AUX HI to the meter V input, NORMAL LO and AUX LO to COM '
                                    '(the calibrator senses at the meter terminals).']],
                 caution='Ohms compensation is set by you, not by the program: check it before continuing.'),
    'UAMP': dict(title='Connect for µA / mA',
                 summary='Calibrator AUX output (5560A: VI AUX) to the meter mA/µA and COM inputs; COMP off.',
                 steps=[['Standby', 'The calibrator is in STANDBY while you rewire.'],
                        ['Connect', 'Calibrator AUX HI / LO (5560A: VI AUX and OUTPUT LO) to the meter mA/µA (red) and COM inputs.']],
                 caution='The mA/µA input is fused at 0.44 A: do not exceed the point being tested.'),
    'AMP10': dict(title='Connect for A',
                  summary='Calibrator 20 A output (5560A: 30A) to the meter A and COM inputs.',
                  steps=[['Standby', 'The calibrator is in STANDBY while you rewire.'],
                         ['Connect', 'Calibrator 20 A output and AUX LO (5560A: 30A and OUTPUT LO) to the meter A (red) and COM inputs, '
                                     'with leads rated for 10 A.']],
                  caution='The A input is fused at 11 A.'),
    'TEMP': dict(title='Connect the thermocouple', summary=TEMP_SETUP,
                 steps=[['Standby', 'The calibrator is in STANDBY while you connect.'], ['Meter', TEMP_SETUP.split(' K-type')[0]],
                        ['Connect', 'K-type' + TEMP_SETUP.split(' K-type')[1]]]),
}

spec = {
    'schema': 2,
    'kind': 'manual-reading',
    'options': {'hv_threshold_v': 60, 'auto_ramp': False, 'ir': 'fluke28x', 'table_order': {'F': 0, '3': 1, '4': 2}},
    'source': {'document': 'Fluke 287/289 True-rms Digital Multimeters Calibration Manual',
               'pages': '14-20 (printed): functional checks pp. 15-16, Table 3 p. 17, Table 4 pp. 17-20',
               'cite': 'Fluke 287/289 Calibration Manual, Performance Tests, pp. 14-20 (Tables 3 and 4)',
               'limits': 'Manufacturer display-reading limits (Table 4)',
               'note': ('Display-reading limits as printed (Tables 3 and 4). The manual uses a Fluke 5520A with the scope option; a 5522A or 5560A '
                        'can be used where it makes the point (it refuses outputs it cannot make). Steps 25, 29 and 41 are set on the calibrator by '
                        'hand. Allow the meter to reach room temperature first (can take several hours). Readings can be typed or read over the '
                        'IR cable; with IR the program also checks the meter\'s function, range and REL / Low Pass state before recording.')},
    'models': {'287': dict(name='Fluke 287', brand='Fluke', model_note='Fluke 287 True-rms logging multimeter'),
               '289': dict(name='Fluke 289', brand='Fluke', model_note='Fluke 289 True-rms industrial logging multimeter')},
    'groups': GROUPS,
    'steps': steps,
}

if __name__ == '__main__':
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    for m in ('287', '289'):
        print(m, sum(1 for s in steps if m in s['models']), 'points')
