"""Builds specs/fluke_753_754_pv.json for the Fluke 753 / 754 Documenting Process Calibrator (engine fluke_753_754.py, a subclass of handheld_dmm.App).

    python3 specs/build_fluke_753_754_spec.py

Source: Fluke 753/754 Calibration Manual (Rev 0, Nov 2011), chapter 'Performance Verification Tests', printed pp. 9-32 (PDF pages 17-40).  Every limit, input, range, frequency and
temperature type was read from RENDERED PAGE IMAGES (pdftoppm, 150 and 300 dpi) and read twice (second reading: the arithmetic check below against the manual's own accuracy
specification, printed pp. 5-8 (PDF pages 13-16), plus a comparison with the extracted text in tests/test_fluke_753_754_points.py).  Extracted text was used only to find pages.

ONE FAMILY SPEC, TWO MODELS (as the 110 / 170 / 323 families): 753 = 90 points, 754 = 91 (the HART mode check, 'HART Mode Verification (754 Only)', printed p. 30-31).

TWO DIRECTIONS (owner rule): the calibrator is the UUT here, so a point is either
  direction 'measure'  the UUT MEASURES (its input): the lab calibrator (Fluke 5522A is the one the manual names, Table 2; 5560A / 5520A are offered by the engine) SOURCES the value,
                       the technician types the UUT display.  Uncertainty: the calibrator's published 'output' sheet.  Sections are titled '... Measure (UUT input)'.
  direction 'source'   the UUT SOURCES (its output): MANUAL ENTRY ONLY, the technician types the reading of the external measuring instrument (the manual: Fluke 8508A DMM, Tektronix
                       FCA3000 counter) - no meter driver, no automatic reading.  Uncertainty: the lab's MEASURING standard, whose 'input'-direction sheet gives the standard uncertainty;
                       the owner picks one per point (3458A default; 34461A / 34465A when their sheets exist).  Sections are titled '... Source (UUT output)'.
  (HART: communication pass / fail, no direction, no uncertainty.)

THERMOCOUPLE: the manual tests Type K only (Table 13 measure, Table 14 source).  The other types in the specification table (E N J T B R S C L U BP XK, printed p. 7) are NOT in any
verification table, so no point uses them.  Every temperature point carries tc 'K'; the engine sends it to the calibrator as TC_TYPE.
  MEASURE (Table 13): the manual sources DC millivolts from the 5522A through copper / Type K junctions in a lag bath and subtracts the lag-bath millivolts.  This procedure sources the
  Type K thermocouple simulation of the calibrator instead (TC_TYPE K, degrees C, the calibrator's own reference junction): same three temperatures (-180, 0, 1300 C), same limits,
  no lag bath.  DEVIATION FROM THE MANUAL'S METHOD: owner question in the report.  The manual's millivolt equivalents are kept in the step (mv_equivalent).
  SOURCE (Table 14): the UUT sources Type K; the external DMM reads millivolts; the technician adds the lag-bath millivolts (Table 13 reference chart, 18-28 C) as the manual says and types
  the corrected value (not automated).
RTD (Pt100, alpha 385): MEASURE (Tables 15, 16) the calibrator sources the resistance equivalent the manual prints (27.096 / 138.505 / 369.712 ohm) with the calibrator's 4-wire (Table 15)
  or no (Table 16) compensation set by the technician; the UUT reads degrees C.  SOURCE (Table 17): the UUT sources Pt100 (385), the external DMM reads ohms.

PRINTED MISPRINTS / ODDITIES (limits are never changed silently; every one is in the step's note and in the report's source note):
  * Table 3, 30.0000 V range, input 30 V: the maximum 1-year is printed 29.9870 (below the minimum 29.9935).  The row is symmetric like its neighbours (+-0.0065 = 0.02 % + 0.0005 V),
    so 30.0065 is used; the printed value is kept in step.printed_text.  UNVERIFIED against a second source.
  * Table 4, 300.0 V range, last row: 295 V at 50 Hz (the other 300 V rows use 40 Hz and 500 Hz; the specification is 40 - 500 Hz).  Kept as printed (50 Hz); flagged.
  * Table 8: the first two rows print the range as '100.000' without a unit; mV is inferred from the output (10 mV, 0.1 V) and the limits (9.9940 ..).
  * Tables 15 / 16 print a negative range as '-179.93 to -180.07' (high first): stored low -180.07, high -179.93.
  * The text before Table 12 says 'Table 11' for the frequency limits; Table 12 is meant.
  * The specification (p. 5) has no 100 mV dc range row (3 V, 30 V, 300 V only): the 100 mV rows of Table 3 are 0.02 % + 0.005 mV (arithmetic, UNVERIFIED).
  * 1-year limits are the ones used (the limits interval a lab uses is the owner's call); the 2-year limits are stored in step.limits_2y.
The builder recomputes each limit from the printed accuracy statement (Decimal) and records any disagreement in step.check; it aborts only on a structural error.
"""
from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_753_754_pv.json'
DOCUMENT = 'Fluke 753/754 Documenting Process Calibrator - Calibration Manual (Rev 0, 11/2011)'
MODELS = ('753', '754')
BOTH = ('753', '754')
ONLY_754 = ('754',)
EXPECTED = {'753': 90, '754': 91}

UNITS = {'V': ('1', 'V'), 'mV': ('0.001', 'V'), 'A': ('1', 'A'), 'mA': ('0.001', 'A'), 'Ω': ('1', 'ohm'), 'kΩ': ('1000', 'ohm'), 'Hz': ('1', 'Hz'), 'kHz': ('1000', 'Hz'), '°C': ('1', 'degC')}
SYM = {'V': 'V', 'mV': 'mV', 'A': 'A', 'mA': 'mA', 'Ω': 'ohm', 'kΩ': 'kohm', 'Hz': 'Hz', 'kHz': 'kHz', '°C': 'degC'}   # ASCII names for the report text (report_pdf.ascii_unit does the rest)

# function text per section (the manual names the functions; softkey / key names of the UUT are not given: UNVERIFIED)
FN = {
    'dcv_m': 'DC volts measure', 'acv_m': 'AC volts measure', 'dci_m': 'DC current (mA) measure', 'ohm_m': 'Resistance measure', 'hz_m': 'Frequency measure',
    'tc_m': 'Thermocouple measure (Type K, ITS-90, internal reference, degC)', 'rtd4_m': 'RTD measure Pt100 (385), ITS-90, four-wire', 'rtd3_m': 'RTD measure Pt100 (385), ITS-90, three-wire',
    'dcv_s': 'DC volts source', 'dci_s': 'DC current (mA) source', 'sim_s': 'mA source: Simulate Transmitter', 'ohm_s': 'Resistance source', 'hz_s': 'Frequency source',
    'tc_s': 'Thermocouple source (Type K, linear mode, ITS-90, internal reference, degC)', 'rtd_s': 'RTD source Pt100 (385), ITS-90', 'loop': 'Loop power', 'hart': 'HART mode (754)',
}

SECT = {
    '3': 'DC Volts Measure (UUT input)', '4': 'AC Volts Measure (UUT input)', '5': 'DC Current Measure (UUT input)', '6': 'Resistance Measure (UUT input)',
    '7': 'Frequency Measure (UUT input)', '8': 'DC Volts Source (UUT output)', '9': 'DC Current Source (UUT output)', '10': 'Simulate Transmitter (UUT output)',
    '11': 'Resistance Source (UUT output)', '12': 'Frequency Source (UUT output)', '13': 'Thermocouple Measure Type K (UUT input)', '14': 'Thermocouple Source Type K (UUT output)',
    '15': 'RTD Measure Pt100 four-wire (UUT input)', '16': 'RTD Measure Pt100 three-wire (UUT input)', '17': 'RTD Source Pt100 (UUT output)', 'LP': 'Loop Power (UUT output)',
    'H': 'HART Mode (754 only)'}
PAGES = {'3': 11, '4': 12, '5': 14, '6': 15, '7': 16, '8': 17, '9': 18, '10': 20, '11': 21, '12': 22, '13': 25, '14': 26, '15': 27, '16': 28, '17': 29, 'LP': 30, 'H': 31}   # printed pages


def r(rng, nominal, lo1, hi1, lo2, hi2, unit, **kw):
    """One table row: UUT range text, the input / output as printed, 1-year min / max, 2-year min / max (display unit `unit`)."""
    return dict(rng=rng, nominal=nominal, lo1=lo1, hi1=hi1, lo2=lo2, hi2=hi2, unit=unit, **kw)


# ---- Table 3  DC volts measurement (calibrator DC volts; the 5522A drives it): printed p. 11
T3 = [
    r('100.000 mV', '0', '-0.005', '0.005', '-0.005', '0.005', 'mV', applied='0', nom_disp='0', unit_in='mV'),
    r('100.000 mV', '0.1', '99.975', '100.025', '99.965', '100.035', 'mV', applied='0.1', nom_disp='100', unit_in='mV'),
    r('100.000 mV', '-0.1', '-100.025', '-99.975', '-100.035', '-99.965', 'mV', applied='-0.1', nom_disp='-100', unit_in='mV'),
    r('3.00000 V', '0', '-0.00005', '0.00005', '-0.00005', '0.00005', 'V', applied='0', nom_disp='0'),
    r('3.00000 V', '1.0', '0.99975', '1.00025', '0.99965', '1.00035', 'V', applied='1', nom_disp='1'),
    r('3.00000 V', '2.0', '1.99955', '2.00045', '1.99935', '2.00065', 'V', applied='2', nom_disp='2'),
    r('3.00000 V', '3', '2.99935', '3.00065', '2.99905', '3.00095', 'V', applied='3', nom_disp='3'),
    r('3.00000 V', '-3', '-3.00065', '-2.99935', '-3.00095', '-2.99905', 'V', applied='-3', nom_disp='-3'),
    r('30.0000 V', '0', '-0.0005', '0.0005', '-0.0005', '0.0005', 'V', applied='0', nom_disp='0'),
    r('30.0000 V', '30', '29.9935', '30.0065', '29.9905', '30.0095', 'V', applied='30', nom_disp='30', printed=dict(hi1='29.9870'), misprint='3-10'),
    r('30.0000 V', '-30', '-30.0065', '-29.9935', '-30.0095', '-29.9905', 'V', applied='-30', nom_disp='-30'),
    r('300.00 V', '0', '-0.05', '0.05', '-0.05', '0.05', 'V', applied='0', nom_disp='0'),
    r('300.00 V', '295', '294.80', '295.20', '294.74', '295.26', 'V', applied='295', nom_disp='295'),
    r('300.00 V', '-295', '-295.20', '-294.80', '-295.26', '-294.74', 'V', applied='-295', nom_disp='-295'),
]
# ---- Table 4  AC volts measurement (volts rms, Hz): printed p. 12
T4 = [
    r('3.000 V', '0.26', '0.257', '0.263', '0.253', '0.267', 'V', applied='0.26', freq=500),
    r('3.000 V', '3', '2.983', '3.017', '2.966', '3.034', 'V', applied='3', freq=500),
    r('3.000 V', '0.26', '0.257', '0.263', '0.253', '0.267', 'V', applied='0.26', freq=40),
    r('3.000 V', '3', '2.983', '3.017', '2.966', '3.034', 'V', applied='3', freq=40),
    r('30.00 V', '2.6', '2.567', '2.633', '2.53', '2.67', 'V', applied='2.6', freq=500),
    r('30.00 V', '30', '29.830', '30.170', '29.66', '30.34', 'V', applied='30', freq=500),
    r('30.00 V', '2.6', '2.567', '2.633', '2.53', '2.67', 'V', applied='2.6', freq=40),
    r('30.00 V', '30', '29.830', '30.170', '29.66', '30.34', 'V', applied='30', freq=40),
    r('300.0 V', '27', '26.665', '27.335', '26.5', '27.5', 'V', applied='27', freq=500),
    r('300.0 V', '295', '293.325', '296.675', '291.9', '298.2', 'V', applied='295', freq=500),
    r('300.0 V', '27', '26.665', '27.335', '26.5', '27.5', 'V', applied='27', freq=40),
    r('300.0 V', '295', '293.325', '296.675', '291.9', '298.2', 'V', applied='295', freq=50, oddity='4-12'),
]
# ---- Table 5  DC current measurement (mA): printed p. 14
T5 = [
    r('30 mA', '4', '3.995', '4.005', '3.992', '4.008', 'mA', applied='0.004', nom_disp='4'),
    r('30 mA', '20', '19.993', '20.007', '19.990', '20.010', 'mA', applied='0.02', nom_disp='20'),
    r('30 mA', '30', '29.992', '30.008', '29.989', '30.012', 'mA', applied='0.03', nom_disp='30'),
    r('30 mA', '-30', '-30.008', '-29.992', '-30.012', '-29.989', 'mA', applied='-0.03', nom_disp='-30'),
    r('100 mA', '0', '-0.02', '0.02', '-0.03', '0.03', 'mA', applied='0', nom_disp='0'),
    r('100 mA', '100', '99.97', '100.03', '99.96', '100.04', 'mA', applied='0.1', nom_disp='100'),
    r('100 mA', '-100', '-100.03', '-99.97', '-100.04', '-99.96', 'mA', applied='-0.1', nom_disp='-100'),
]
# ---- Table 6  Resistance measurement: printed p. 15 (the display unit of the 10 kohm range limits is kohm: '-0.010 .. 0.010', '9.980 .. 10.020')
T6 = [
    r('10.000 Ω', '0', '-0.050', '0.050', '-0.070', '0.070', 'Ω', applied='0', nom_disp='0'),
    r('10.000 Ω', '10', '9.945', '10.055', '9.923', '10.077', 'Ω', applied='10', nom_disp='10'),
    r('100.00 Ω', '0', '-0.05', '0.05', '-0.07', '0.07', 'Ω', applied='0', nom_disp='0'),
    r('100.00 Ω', '100', '99.90', '100.10', '99.86', '100.14', 'Ω', applied='100', nom_disp='100'),
    r('1000.0 Ω', '0', '-0.5', '0.5', '-0.7', '0.7', 'Ω', applied='0', nom_disp='0'),
    r('1000.0 Ω', '1000', '999.0', '1001.0', '998.6', '1001.4', 'Ω', applied='1000', nom_disp='1000'),
    r('10.000 kΩ', '0', '-0.010', '0.010', '-0.015', '0.015', 'kΩ', applied='0', nom_disp='0'),
    r('10.000 kΩ', '10000', '9.980', '10.020', '9.970', '10.030', 'kΩ', applied='10000', nom_disp='10'),
]
# ---- Table 7  Frequency measurement (calibrator volts rms, the UUT reads Hz / kHz): printed p. 16; one limit pair for 1 and 2 years
T7 = [
    r('<20 Hz', '10 Hz', '9.95', '10.05', '9.95', '10.05', 'Hz', applied='0.3', freq=10, nom_disp='10'),
    r('>20 Hz', '150 Hz', '149.5', '150.5', '149.5', '150.5', 'Hz', applied='0.3', freq=150, nom_disp='150'),
    r('>20 Hz', '1.2 kHz', '1.195', '1.205', '1.195', '1.205', 'kHz', applied='1', freq=1200, nom_disp='1.2'),
    r('>20 Hz', '12 kHz', '11.95', '12.05', '11.95', '12.05', 'kHz', applied='1', freq=12000, nom_disp='12'),
    r('>20 Hz', '49 kHz', '48.95', '49.05', '48.95', '49.05', 'kHz', applied='2', freq=49000, nom_disp='49'),
]
# ---- Table 8  DC volts source (UUT output, the external DMM reads): printed p. 17
T8 = [
    r('100.000', '10 mV', '9.9940', '10.0060', '9.9935', '10.0065', 'mV', uut=('DCV', '0.01'), nom_disp='10', range_note='range printed without a unit'),
    r('100.000', '0.1 V', '99.9850', '100.0150', '99.9800', '100.0200', 'mV', uut=('DCV', '0.1'), nom_disp='100', range_note='range printed without a unit; output printed 0.1 V, limits in mV'),
    r('1.00000 V', '0.15 V', '0.14994', '0.15007', '0.14993', '0.15007', 'V', uut=('DCV', '0.15'), nom_disp='0.15'),
    r('1.00000 V', '1 V', '0.99985', '1.00015', '0.99980', '1.00020', 'V', uut=('DCV', '1'), nom_disp='1'),
    r('15.0000 V', '1.5 V', '1.49935', '1.50065', '1.49928', '1.50073', 'V', uut=('DCV', '1.5'), nom_disp='1.5'),
    r('15.0000 V', '10 V', '9.99850', '10.00150', '9.99800', '10.00200', 'V', uut=('DCV', '10'), nom_disp='10'),
]
# ---- Table 9  DC current source (mA): printed p. 18
T9 = [
    r('22.000 mA', '2 mA', '1.99680', '2.00320', '1.99660', '2.00340', 'mA', uut=('DCI', '0.002'), nom_disp='2'),
    r('22.000 mA', '4 mA', '3.99660', '4.00340', '3.99620', '4.00380', 'mA', uut=('DCI', '0.004'), nom_disp='4'),
    r('22.000 mA', '12 mA', '11.99580', '12.00420', '11.99460', '12.00540', 'mA', uut=('DCI', '0.012'), nom_disp='12'),
    r('22.000 mA', '21 mA', '20.99490', '21.00510', '20.99280', '21.00720', 'mA', uut=('DCI', '0.021'), nom_disp='21'),
]
# ---- Table 10  Simulate transmitter (mA sink; the 5522A supplies 8 V dc, its value is not critical): printed p. 20
T10 = [
    r('22.000 mA', '4', '3.99220', '4.00780', '3.99140', '4.00860', 'mA', uut=('DCI', '0.004'), nom_disp='4', loop_supply_v='8'),
    r('22.000 mA', '21', '20.98880', '21.01120', '20.98460', '21.01540', 'mA', uut=('DCI', '0.021'), nom_disp='21', loop_supply_v='8'),
]
# ---- Table 11  Resistance source: printed p. 21
T11 = [
    r('10.000 Ω', '0.1 Ω', '0.0900', '0.1100', '0.0850', '0.1150', 'Ω', uut=('OHM', '0.1'), nom_disp='0.1'),
    r('10.000 Ω', '1 Ω', '0.9899', '1.0101', '0.9849', '1.0152', 'Ω', uut=('OHM', '1'), nom_disp='1'),
    r('10.000 Ω', '10 Ω', '9.9890', '10.0110', '9.9835', '10.0165', 'Ω', uut=('OHM', '10'), nom_disp='10'),
    r('100.00 Ω', '20 Ω', '19.978', '20.022', '19.967', '20.033', 'Ω', uut=('OHM', '20'), nom_disp='20'),
    r('100.00 Ω', '100 Ω', '99.970', '100.030', '99.955', '100.045', 'Ω', uut=('OHM', '100'), nom_disp='100'),
    r('1000.0 Ω', '200 Ω', '199.76', '200.24', '199.64', '200.36', 'Ω', uut=('OHM', '200'), nom_disp='200'),
    r('1000.0 Ω', '1000 Ω', '999.60', '1000.40', '999.40', '1000.60', 'Ω', uut=('OHM', '1000'), nom_disp='1000'),
    r('10.000 kΩ', '2 kΩ', '1.9966', '2.0034', '1.9944', '2.0056', 'kΩ', uut=('OHM', '2000'), nom_disp='2'),
    r('10.000 kΩ', '10 kΩ', '9.9950', '10.0050', '9.9920', '10.0080', 'kΩ', uut=('OHM', '10000'), nom_disp='10'),
]
# ---- Table 12  Frequency source (counter): printed p. 22.  Frequency @ 1 Vpp (6 rows) and @ 7.5 Vpp (1 row); one limit pair for 1 and 2 years
T12 = [
    r('10.99 Hz', '5 Hz Sine', '4.99', '5.01', '4.99', '5.01', 'Hz', uut=('FREQ', '5'), wave='sine', vpp='1', nom_disp='5'),
    r('1099.9 Hz', '1 kHz Sine', '999.9', '1000.1', '999.9', '1000.1', 'Hz', uut=('FREQ', '1000'), wave='sine', vpp='1', nom_disp='1000'),
    r('21.999 kHz', '10 kHz Sine', '9.998', '10.002', '9.998', '10.002', 'kHz', uut=('FREQ', '10000'), wave='sine', vpp='1', nom_disp='10'),
    r('50 kHz', '49 kHz Sine', '48.995', '49.005', '48.995', '49.005', 'kHz', uut=('FREQ', '49000'), wave='sine', vpp='1', nom_disp='49'),
    r('10.99 Hz', '5 Hz Square', '4.99', '5.01', '4.99', '5.01', 'Hz', uut=('FREQ', '5'), wave='square', vpp='1', nom_disp='5'),
    r('1099.9 Hz', '1 kHz Square', '999.9', '1000.1', '999.9', '1000.1', 'Hz', uut=('FREQ', '1000'), wave='square', vpp='1', nom_disp='1000'),
    r('109.99 Hz', '50 Hz Square', '49.9', '50.1', '49.9', '50.1', 'Hz', uut=('FREQ', '50'), wave='square', vpp='7.5', nom_disp='50'),
]
# ---- Table 13  Temperature measure, Type K, ITS-90: printed p. 25 (the manual's input is dc mV referenced to 0 C; here the calibrator sources the temperature, TC_TYPE K)
T13 = [
    r('Type K', '-180', '-180.9', '-179.1', '-181.2', '-178.8', '°C', applied='-180', tc='K', nom_disp='-180', mv='-5.550'),
    r('Type K', '0', '-0.5', '0.5', '-0.6', '0.6', '°C', applied='0', tc='K', nom_disp='0', mv='0.000'),
    r('Type K', '1300', '1299.1', '1300.9', '1298.8', '1301.2', '°C', applied='1300', tc='K', nom_disp='1300', mv='52.410'),
]
# ---- Table 14  Temperature source, Type K, ITS-90: printed p. 26 (UUT output -180 / 0 / 1300 C; the DMM reads dc mV, limits in mV)
T14 = [
    r('Type K', '-180 °C', '-5.5616', '-5.5390', '-5.5653', '-5.5353', 'mV', uut=('DCV', '-0.0055504'), tc='K', nom_disp='-5.5504', out_c='-180'),
    r('Type K', '0 °C', '-0.0197', '0.0197', '-0.0237', '0.0237', 'mV', uut=('DCV', '0.0'), tc='K', nom_disp='0.0000', out_c='0'),
    r('Type K', '1300 °C', '52.3928', '52.4277', '52.3893', '52.4312', 'mV', uut=('DCV', '0.0524103'), tc='K', nom_disp='52.4103', out_c='1300'),
]
# ---- Tables 15 / 16  RTD measure Pt100 (385): printed pp. 27 / 28.  (input degC, resistance ohm, 1-year, 2-year ranges as printed 'a to b')
T15 = [
    r('Pt100 (385)', '-180', '-180.07', '-179.93', '-180.14', '-179.86', '°C', applied='27.096', rtd='Pt385-100', nom_disp='-180'),
    r('Pt100 (385)', '100', '99.93', '100.07', '99.86', '100.14', '°C', applied='138.505', rtd='Pt385-100', nom_disp='100'),
    r('Pt100 (385)', '780', '779.79', '780.21', '779.59', '780.41', '°C', applied='369.712', rtd='Pt385-100', nom_disp='780'),
]
T16 = [
    r('Pt100 (385)', '-180', '-180.47', '-179.53', '-180.54', '-179.46', '°C', applied='27.096', rtd='Pt385-100', nom_disp='-180'),
    r('Pt100 (385)', '100', '99.53', '100.47', '99.46', '100.54', '°C', applied='138.505', rtd='Pt385-100', nom_disp='100'),
    r('Pt100 (385)', '780', '779.39', '780.61', '779.19', '780.81', '°C', applied='369.712', rtd='Pt385-100', nom_disp='780'),
]
# ---- Table 17  RTD source Pt100 (385): printed p. 29 (UUT output degC; the DMM reads ohms)
T17 = [
    r('Pt100 (385)', '-180 °C', '27.075', '27.118', '27.054', '27.139', 'Ω', uut=('OHM', '27.096'), rtd='Pt385-100', nom_disp='27.096', out_c='-180'),
    r('Pt100 (385)', '100 °C', '138.487', '138.524', '138.468', '138.543', 'Ω', uut=('OHM', '138.505'), rtd='Pt385-100', nom_disp='138.505', out_c='100'),
    r('Pt100 (385)', '780 °C', '369.6707', '369.7532', '369.630', '369.795', 'Ω', uut=('OHM', '369.712'), rtd='Pt385-100', nom_disp='369.712', out_c='780'),
]
# ---- Loop power: printed p. 30: no-load voltage 23.4 V to 28.6 V on the external DMM
TLP = [r('Loop power', '23.4 V to 28.6 V', '23.4', '28.6', '23.4', '28.6', 'V', uut=('DCV', '26'), nom_disp='26')]

TABLES = [('3', T3, 'dcv_m'), ('4', T4, 'acv_m'), ('5', T5, 'dci_m'), ('6', T6, 'ohm_m'), ('7', T7, 'hz_m'), ('8', T8, 'dcv_s'), ('9', T9, 'dci_s'), ('10', T10, 'sim_s'), ('11', T11, 'ohm_s'),
          ('12', T12, 'hz_s'), ('13', T13, 'tc_m'), ('14', T14, 'tc_s'), ('15', T15, 'rtd4_m'), ('16', T16, 'rtd3_m'), ('17', T17, 'rtd_s'), ('LP', TLP, 'loop')]
MEASURE = {'3', '4', '5', '6', '7', '13', '15', '16'}

# hook-up groups (diagrams/hook_fluke753_<GROUP>.png, drawn by specs/build_hookups_753.py from the owner's photo and the manual's figures)
GROUP_OF = {'3': 'MEAS_V', '4': 'MEAS_V', '5': 'MEAS_MA', '6': 'MEAS_OHM', '7': 'MEAS_V', '8': 'SRC_V', '9': 'SRC_MA', '10': 'SRC_SIM', '11': 'SRC_OHM', '12': 'SRC_FREQ',
            '13': 'MEAS_TC', '14': 'SRC_TC', '15': 'MEAS_RTD4', '16': 'MEAS_RTD3', '17': 'SRC_OHM', 'LP': 'LOOP', 'H': 'HART'}

# ---- accuracy statements (printed pp. 5-8), per table / range: (pct_1y, floor_1y, pct_2y, floor_2y) in the display unit of the limits (or None = not checked arithmetically)
ACC = {
    ('3', '100.000 mV'): ('0.02', '0.005', '0.03', '0.005'), ('3', '3.00000 V'): ('0.02', '0.00005', '0.03', '0.00005'), ('3', '30.0000 V'): ('0.02', '0.0005', '0.03', '0.0005'),
    ('3', '300.00 V'): ('0.05', '0.05', '0.07', '0.05'),
    ('4', '3.000 V'): ('0.5', '0.002', '1.0', '0.004'), ('4', '30.00 V'): ('0.5', '0.02', '1.0', '0.04'), ('4', '300.0 V'): ('0.5', '0.2', '1.0', '0.2'),
    ('5', '30 mA'): ('0.01', '0.005', '0.015', '0.007'), ('5', '100 mA'): ('0.01', '0.02', '0.015', '0.03'),
    ('6', '10.000 Ω'): ('0.05', '0.050', '0.07', '0.070'), ('6', '100.00 Ω'): ('0.05', '0.05', '0.07', '0.07'), ('6', '1000.0 Ω'): ('0.05', '0.5', '0.07', '0.7'),
    ('6', '10.000 kΩ'): ('0.10', '0.010', '0.15', '0.015'),
    ('8', '100.000'): ('0.01', '0.005', '0.015', '0.005'), ('8', '1.00000 V'): ('0.01', '0.00005', '0.015', '0.00005'), ('8', '15.0000 V'): ('0.01', '0.0005', '0.015', '0.0005'),
    ('9', '22.000 mA'): ('0.01', '0.003', '0.02', '0.003'), ('10', '22.000 mA'): ('0.02', '0.007', '0.04', '0.007'),
    ('11', '10.000 Ω'): ('0.01', '0.010', '0.015', '0.015'), ('11', '100.00 Ω'): ('0.01', '0.02', '0.015', '0.03'), ('11', '1000.0 Ω'): ('0.02', '0.2', '0.03', '0.3'),
    ('11', '10.000 kΩ'): ('0.02', '0.003', '0.03', '0.005'),
}
FLAT = {   # absolute half-widths (1-year, 2-year) in the display unit
    ('7', '10 Hz'): ('0.05', '0.05'), ('7', '150 Hz'): ('0.5', '0.5'), ('7', '1.2 kHz'): ('0.005', '0.005'), ('7', '12 kHz'): ('0.05', '0.05'), ('7', '49 kHz'): ('0.05', '0.05'),
    ('13', '-180'): ('0.9', '1.2'), ('13', '0'): ('0.5', '0.6'), ('13', '1300'): ('0.9', '1.2'),
    ('15', '-180'): ('0.07', '0.14'), ('15', '100'): ('0.07', '0.14'), ('16', '-180'): ('0.47', '0.54'), ('16', '100'): ('0.47', '0.54'),
}
PCT_PLUS = {('15', '780'): ('0.02', '0.05', '0.04', '0.10'), ('16', '780'): ('0.02', '0.45', '0.04', '0.50')}   # 3-wire: + 0.4 degC (p. 8 note 2)


def decimals(t: str) -> int:
    return max(0, -D(t).as_tuple().exponent)


def fmt(d: D) -> str:
    return format(d, 'f')


def clean(v) -> float:
    return float(f'{float(v):.9g}')


def formula_check(table, row):
    """List of disagreements between a row's printed limits and the accuracy statement (empty = agrees within the last printed digit)."""
    out = []
    key = (table, row['rng'])
    nominal = D(row['nom_disp']) if row.get('nom_disp') not in (None, '') else None
    if nominal is None:
        return out
    lim = {'1y': (D(row['lo1']), D(row['hi1'])), '2y': (D(row['lo2']), D(row['hi2']))}
    halves = None
    if key in ACC:
        p1, f1, p2, f2 = (D(x) for x in ACC[key])
        halves = {'1y': abs(nominal) * p1 / 100 + f1, '2y': abs(nominal) * p2 / 100 + f2}
    elif (table, row['nom_disp']) in FLAT:
        a, b = FLAT[(table, row['nom_disp'])]
        halves = {'1y': D(a), '2y': D(b)}
    elif (table, row['nom_disp']) in PCT_PLUS:
        p1, f1, p2, f2 = (D(x) for x in PCT_PLUS[(table, row['nom_disp'])])
        halves = {'1y': abs(nominal) * p1 / 100 + f1, '2y': abs(nominal) * p2 / 100 + f2}
    if halves is None:
        return out
    for per in ('1y', '2y'):
        lo, hi = lim[per]
        tol = D(1).scaleb(-max(decimals(row['lo1']), decimals(row['hi1']), decimals(row['lo2']), decimals(row['hi2'])))     # one unit of the last printed digit
        for side, got, want in (('low', nominal - lo, halves[per]), ('high', hi - nominal, halves[per])):
            if abs(got - want) > tol * D('1.0001'):
                out.append(f'{per} {side}: printed offset {fmt(got)}, accuracy statement {fmt(want.quantize(tol) if tol else want)}')
    return out


def build_steps():
    steps, n = [], 0
    for table, rows, fn in TABLES:
        for i, row in enumerate(rows, 1):
            n += 1
            unit = row['unit']
            factor, base = UNITS[unit]
            source = table not in MEASURE
            nom_disp = row.get('nom_disp', row['nominal'])
            lo1, hi1, lo2, hi2 = row['lo1'], row['hi1'], row['lo2'], row['hi2']
            if D(lo1) > D(hi1):
                raise SystemExit(f'table {table} row {i}: low above high')
            if not D(lo1) <= D(nom_disp) <= D(hi1):
                raise SystemExit(f'table {table} row {i}: nominal {nom_disp} outside {lo1} .. {hi1}')
            step = dict(table=table, step=n, id=f'{table}-{i}', ref=f'Table {table} row {i}' if table not in ('LP', 'H') else 'Loop Power', page=PAGES[table], section=SECT[table], models=list(BOTH),
                        direction='source' if source else 'measure', range=row['rng'], display_unit=unit, factor=float(D(factor)), base_unit=base, low=lo1, high=hi1, test='numeric',
                        limits_2y=dict(low=lo2, high=hi2), nominal=clean(D(nom_disp) * D(factor)), group=GROUP_OF[table], tol_text=f'Table {table} (1-year): {lo1} to {hi1} {unit}')
            notes = []
            sw_range = row['rng']
            if source:
                kind, uval = row['uut']
                step['kind'] = kind
                step['uut'] = dict(kind=kind, value=float(D(uval)), frequency=float(row['freq']) if row.get('freq') else (float(D(row['uut'][1])) if kind == 'FREQ' else None),
                                   unit=base, sheet_direction='input')
                step['applied'] = None
                step['unc_direction'] = 'input'
                step['switch'] = FN[fn]                      # the function only: the 'Change the function' prompt is shown when the function changes; the value to set is in the point's own window (dsb_out)
                out_txt = {'8': f'DC volts {row["nominal"]}', '9': f'DC current {row["nominal"]}', '10': f'Simulate transmitter {row["nominal"]} mA', '11': f'Resistance {row["nominal"]}',
                           '12': f'{row["nominal"]}, {row["vpp"]} Vpp' if table == '12' else '', '14': f'Type K {row["nominal"]}', '17': f'Pt100 (385) {row["nominal"]}', 'LP': 'Loop power on (no load)'}[table]
                step['dsb_out'] = f'UUT sources {out_txt} (read on the external meter; type the reading)'
                step['dsb_desc'] = f'{SECT[table].split(" (")[0]} {out_txt}' + (f', {sw_range} range' if table not in ('LP', '12', '14', '17') else '')
                step['report_desc'] = f'Output: {out_txt}' + (f' (UUT range {sw_range}' + (' mV' if table == '8' and sw_range == '100.000' else '') + ')' if table in ('8', '9', '10', '11') else '')
                notes.append('The UUT SOURCES this value: manual entry only. Type the reading of the external measuring instrument (the manual: Fluke 8508A DMM; the 12 Hz-50 kHz points: Tektronix FCA3000 counter). '
                             'The measuring standard whose uncertainty is printed is chosen per point (right-click the point > Uncertainty standard; 3458A is the default).')
                if table == '10':
                    step['kind'] = 'DCV'                 # the ENGINE's output kind: the calibrator supplies the loop (8 V dc); the point itself is the UUT's mA output (step['uut'] kind DCI)
                    step['applied'] = dict(value=float(D(row['loop_supply_v'])), frequency=None)
                    step['loop_supply'] = True
                    step['dsb_out'] = f'UUT sources Simulate transmitter {row["nominal"]} mA; the calibrator supplies 8 V dc (read the current on the external meter; type the reading)'
                    notes.append('The calibrator (5522A, or the 5560A / 5520A chosen) supplies 8 V dc as the loop supply (the program sets it, DC, 0 Hz); its value is not critical (printed p. 19), a battery can do. '
                                 'The calibrator VALUE is not part of the uncertainty. The text of step 7 (p. 19) says 22 mA; Table 10 prints 21 mA (limits 20.98880 to 21.01120): the table is used.')
                if table == '12':
                    step['waveform'] = row['wave']
                    notes.append(f'{row["wave"].capitalize()} wave, {row["vpp"]} Vpp. Check the waveform on the Fluke 123 (channel A): for the square wave a positive square wave, 50 % duty (+-5 %), amplitude {row["vpp"]} V peak-to-peak '
                                 'as set; for the sine wave the correct frequency, waveform and amplitude (printed p. 21). Not recorded by the program.')
                if table == '14':
                    step['tc'] = 'K'
                    step['mv_note'] = 'add the lag-bath millivolts (Table 13 reference chart, Type K ITS-90, 18-28 C) to the DMM reading, then type the corrected value'
                    notes.append('Type K, linear mode, ITS-90, internal reference, degC (the UUT is set to Type K). Printed p. 25: add the millivolt equivalent of the Type K junction at the lag-bath temperature (Table 13 chart: '
                                 '18 C 0.718, 19 0.758, 20 0.798, 21 0.838, 22 0.879, 23 0.919, 24 0.960, 25 1.000, 26 1.041, 27 1.081, 28 1.122 mV) to the DMM reading and type the corrected value. Not automated. '
                                 'Wait at least 1 minute for thermal emfs and 15 minutes for the lag bath (printed p. 25).')
                if table == '17':
                    step['rtd'] = row['rtd']
                    notes.append('Pt100 (385), ITS-90. DMM in four-wire ohms, autorange; four-wire at the DMM, two wires at the UUT (Figure 8).')
                if table == '11':
                    notes.append('DMM in four-wire ohms: 200 ohm range for the first five points, autorange after (printed p. 20: the low range supplies too much current into the UUT).')
                if table == 'LP':
                    step['uut']['value'] = 26.0
                    notes.append('UUT: SETUP, ENTER, select Loop Power, ENTER (printed p. 30). Type the no-load voltage the DMM shows; the limits are 23.4 V to 28.6 V. The uncertainty is the meter\'s at 26 V (the middle of the window).')
                if table in ('8', '9'):
                    notes.append('UUT range printed ' + sw_range + (' (' + row['range_note'] + ')' if row.get('range_note') else '') + '.')
            else:
                kind = {'3': 'DCV', '4': 'ACV', '5': 'DCI', '6': 'OHM', '7': 'ACV', '13': 'TEMP', '15': 'OHM', '16': 'OHM'}[table]
                step['kind'] = kind
                a_val = float(D(row['applied']))
                step['applied'] = dict(value=a_val, frequency=float(row['freq']) if row.get('freq') else None)
                step['switch'] = f'{FN[fn]}: lock the UUT on the {sw_range} range' if table in ('3', '4', '5', '6') else (f'{FN[fn]}: use the {sw_range} range' if table == '7' else FN[fn])
                step['unc_direction'] = 'output'
                if table == '3':
                    notes.append('The manual drives the 5522A (Figure 1); calibrator DC volts at the input value; lock the UUT range with the Range softkey.')
                if table == '4':
                    notes.append('Let the output become stable before the reading (printed p. 12).')
                if table == '5':
                    step['series_ref'] = dict(kind='DCI', value=a_val)          # owner decision 2026-10-26: the Keysight 3458A in series replaces the manual's 8508A; its typed reading, its 'input' sheet
                    notes.append('The manual puts a Fluke 8508A in series (Figure 2) and has you edit the 5522A output until the 8508A shows the correct value (printed p. 13). Owner decision: the Keysight 3458A (dc current) '
                                 'is in series instead. First window: TYPE the 3458A reading (recorded, not judged). Second window: TYPE the UUT display; ONLY the UUT display is compared with the printed limits '
                                 '(unchanged). The program sets the calibrator to the nominal and sends nothing else: if the 3458A is not at the nominal, adjust the 5522A output on its front panel as the manual does '
                                 '(UNVERIFIED front-panel step). The uncertainty is the 3458A dc-current specification (input sheet), not the calibrator alone. Disconnect the jumpers on the three common jacks of the UUT if present.')
                if table == '6':
                    notes.append('Four-wire connection at the 5522A, two wires at the UUT, two-wire compensation ON at the calibrator (printed p. 15, Figure 3): the program does not set the compensation; set it on the front panel (UNVERIFIED command).')
                if table == '7':
                    notes.append('Select the <20 Hz range for the first point, the >=20 Hz range after it (printed p. 16). The calibrator output is a sine wave in volts rms at the frequency (waveform not stated: sine assumed, UNVERIFIED). '
                                 'The reading is the frequency; the Uncertainty is the lab\'s Frequency - Measure CMC alone (as the 170 series).')
                    step['unc_kind'] = 'FREQ'
                    step['settle'] = 5
                    step['no_freq_suffix'] = True
                    step['report_desc'] = f'{sw_range} range, {row["applied"]} V rms applied'
                if table == '13':
                    step['tc'] = row['tc']
                    step['mv_equivalent'] = row['mv']
                    step['settle'] = 30
                    step['report_desc'] = f'Thermocouple Type K measure, {row["nominal"]} degC (calibrator Type K simulation)'
                    notes.append(f'Type K, ITS-90, internal reference, degC. DEVIATION from the manual\'s method (dc millivolts through a lag bath, printed p. 23): the calibrator sources the Type K thermocouple simulation, TC_TYPE K, '
                                 f'{row["nominal"]} C (= {row["mv"]} mV referenced to 0 C, the manual\'s input). Use Type K thermocouple wire from the calibrator TC output to the UUT TC jack.')
                if table in ('15', '16'):
                    step['rtd'] = row['rtd']
                    step['rtd_celsius'] = float(D(row['nom_disp']))
                    notes.append(f'Pt100 (385), ITS-90. The calibrator sources {row["applied"]} ohm = {row["nominal"]} C (the manual\'s resistance equivalent, Table {table}); the UUT reads degC. '
                                 + ('Four-wire connection and four-wire compensation ON at the calibrator (printed p. 26).' if table == '15' else 'Three-wire connection, compensation OFF at the calibrator (printed p. 27). Limits are 0.4 C wider (p. 8 note 2).')
                                 + ' The program does not set the compensation (UNVERIFIED); the manual sets the 5522A to its RTD function, this procedure uses the resistance equivalent.')
                    step['dsb_desc'] = f'RTD Pt100 (385) {"four" if table == "15" else "three"}-wire, {row["nominal"]} C ({row["applied"]} ohm)'
                    step['settle'] = 3
                    step['report_desc'] = f'RTD Pt100 (385) {"four" if table == "15" else "three"}-wire measure, {row["nominal"]} degC ({row["applied"]} ohm applied)'
                if table == '3' and row.get('misprint'):
                    pass
            # printed oddities
            if row.get('printed'):
                step['printed_text'] = dict(high=row['printed']['hi1'], note='PRINTED MISPRINT corrected: the table prints a 1-year maximum of 29.9870 (below the minimum 29.9935); the row is symmetric, so 30.0065 is used')
                step['check'] = dict(verdict='misprint', printed=dict(high=row['printed']['hi1']), used=dict(high=hi1))
                notes.append('PRINTED MISPRINT: Table 3 prints the 1-year maximum of this row as 29.9870 (lower than the minimum 29.9935). Symmetric like its neighbours (+-0.0065 V = 0.02 % + 0.0005 V): 30.0065 V is used. UNVERIFIED against a second source.')
            if row.get('oddity') == '4-12':
                notes.append('Printed as 295 V at 50 Hz; every other 300 V row uses 40 Hz or 500 Hz. Kept as printed (the specification covers 40 Hz - 500 Hz): confirm with the owner.')
            if kind == 'ACV' and table == '4':
                step['settle'] = 5
            if table == '3' and row['rng'] == '100.000 mV':
                notes.append('The specification table (printed p. 5) has no 100 mV range row; the limits follow 0.02 % + 0.005 mV (arithmetic).')
            problems = formula_check(table, row)
            if problems:
                step.setdefault('check', {}).update(arithmetic=problems)
                notes.append('The printed limits differ from the accuracy statement: ' + '; '.join(problems) + ' (stored as printed).')
            step['note'] = ' '.join(notes)
            steps.append(step)
    n += 1
    steps.append(dict(table='H', step=n, id='H-1', ref='HART mode', page=PAGES['H'], section=SECT['H'], models=list(ONLY_754), direction='none', range='', switch=FN['hart'], kind='NONE', display_unit='', factor=1.0,
                      base_unit='', test='visual', applied=None, group='HART',
                      question='Does the 754 recognize the HART transmitter (the Active Device screen shows the model number and tag, PV, PVAO, PV LRV and PV URV)?  Yes = recognized (pass).  No = not recognized (the test has failed: repair is necessary).',
                      note='HART Mode Verification (754 only), printed pp. 31-32: pass / fail only, no calibration. Setup: HART Channel = mA Jack; connect the 754 to a HART transmitter (Rosemount 1151 or 3051, or any HART device) per Figure 15; push HART, enable Loop Power if needed.'))
    return steps


def groups():
    def common(extra):
        return [('Standby', 'Put the calibrator (or the source) in STANDBY before you rewire (in manual mode, put it in STANDBY yourself).')] + extra + [('Check', 'Compare your connections with the picture, then continue.')]
    cal = 'Fluke 5522A (the manual\'s calibrator, Table 2; a 5560A or 5520A can be chosen in the window)'
    return {
        'MEAS_V': dict(title='Change the cables: UUT measures volts / frequency', summary=f'{cal} NORMAL HI / LO -> UUT V jack and the UUT COM jack on the MEASURE side (Figure 1 and Figure 4).',
                       steps=common([('Calibrator', 'NORMAL HI (red) to the UUT right-hand jack labelled V (CAT II 300 V MAX); NORMAL LO (black) to the UUT jack directly below it (MEASURE common).'),
                                     ('UUT', 'Set the UUT to the function and range of the point (the point window says which); lock the range with the Range softkey.')]),
                       caution='Up to 295 V is applied. Use CAT-rated leads and keep clear of the plugs whenever the output is on. Do not force a dual banana plug into two jacks horizontally (printed p. 10).',
                       diagram='diagrams/hook_fluke753_MEAS_V.png'),
        'MEAS_MA': dict(title='Change the cables: UUT measures dc mA', summary=f'{cal} AUX HI -> 3458A (series, reading typed) -> UUT mA jack; UUT MEASURE common -> AUX LO (Figure 2).',
                        steps=common([('Calibrator', 'Calibrator current output (5522A AUX HI / AUX LO) in series with the UUT mA jack (mA Omega RTD, middle top) and the common jack below it (Figure 2). The manual puts an 8508A in series; here the Keysight 3458A (dc current: calibrator AUX HI to the 3458A I terminal, the 3458A LO terminal to the UUT mA jack; terminals UNVERIFIED) is in series and its reading is typed.'),
                                      ('UUT', 'Disconnect the jumpers on the three common jacks if present (printed p. 13). Set the UUT to dc current, lock the range (30 mA, then 100 mA).')]),
                        caution=None, diagram='diagrams/hook_fluke753_MEAS_MA.png'),
        'MEAS_OHM': dict(title='Change the cables: UUT measures resistance', summary=f'{cal} four-wire output, two-wire at the UUT (both HI leads on the UUT mA Omega RTD jack, both LO leads on the jack below it), two-wire compensation ON (Figure 3).',
                         steps=common([('Calibrator', 'Four-wire connection at the calibrator (NORMAL HI / LO and AUX SENSE HI / LO), both HI leads together on the UUT middle top jack (mA Omega RTD) and both LO leads together on the UUT middle bottom jack. Two-wire compensation ON at the calibrator (set on its front panel; the program does not).'),
                                       ('UUT', 'Set the UUT to resistance measurement, lock the range with the Range softkey.')]),
                         caution=None, diagram='diagrams/hook_fluke753_MEAS_OHM.png'),
        'MEAS_TC': dict(title='Change the cables: UUT measures a thermocouple (Type K)', summary='Type K thermocouple wire from the calibrator TC output to the UUT TC mini-plug jack (left, +/-). UUT: Type K, ITS-90, internal reference, degC.',
                        steps=common([('Calibrator', 'Calibrator TC output -> Type K thermocouple wire -> UUT TC jack, polarity as marked. The calibrator simulates a Type K thermocouple (the program sends TC_TYPE K). (The manual itself sources dc mV through a lag bath, Figure 10.)'),
                                      ('UUT', 'Thermocouple measure function, TC Type K, ITS-90, internal reference, degC. Wait about a minute for the connection to settle.')]),
                        caution=None, diagram='diagrams/hook_fluke753_MEAS_TC.png'),
        'MEAS_RTD4': dict(title='Change the cables: UUT measures a four-wire RTD', summary='Four-wire resistance from the calibrator to the UUT: HI leads on the UUT mA Omega RTD and V jacks, LO leads on the two jacks below them (Figure 11); four-wire compensation ON.',
                          steps=common([('Calibrator', 'Four-wire connection and four-wire compensation ON at the calibrator (front panel; the program does not set it). The calibrator output is the resistance equivalent of the temperature.'),
                                        ('UUT', 'RTD measure function, Pt100 (385), ITS-90, four-wire termination.')]),
                          caution=None, diagram='diagrams/hook_fluke753_MEAS_RTD4.png'),
        'MEAS_RTD3': dict(title='Change the cables: UUT measures a three-wire RTD', summary='Three-wire resistance from the calibrator to the UUT (Figure 12); four-wire compensation OFF.',
                          steps=common([('Calibrator', 'Three-wire connection as Figure 12 (a lead on the UUT mA Omega RTD jack, a lead on the V jack, a jumper between the two lower jacks): read from the figure, UNVERIFIED. Compensation OFF at the calibrator.'),
                                        ('UUT', 'RTD measure function, Pt100 (385), ITS-90, three-wire termination.')]),
                          caution=None, diagram='diagrams/hook_fluke753_MEAS_RTD3.png'),
        'SRC_V': dict(title='Change the cables: UUT sources dc volts', summary='UUT SOURCE jacks (VOhm RTD, left top; common below it) -> external DMM INPUT HI / LO (Figure 5).',
                      steps=common([('Meter', 'External DMM (the manual: Fluke 8508A) in dc volts.'),
                                    ('UUT', 'Set the UUT to the dc volts source function at -10 mV and let it warm up for at least 5 minutes before the first reading (printed p. 17). At the end push CLEAR twice to turn the source off.')]),
                      caution=None, diagram='diagrams/hook_fluke753_SRC_V.png'),
        'SRC_MA': dict(title='Change the cables: UUT sources dc mA', summary='UUT mA source jack (middle top) and common below it -> external DMM A input and LO (Figure 6).',
                       steps=common([('Meter', 'External DMM in dc current.'), ('UUT', 'Set the UUT to the dc current source function (NOT simulate transmitter) at 2 mA. Push CLEAR twice at the end (printed p. 18).')]),
                       caution=None, diagram='diagrams/hook_fluke753_SRC_MA.png'),
        'SRC_SIM': dict(title='Change the cables: UUT simulates a transmitter', summary='UUT mA jack and common (as Figure 6) in series with the external DMM (current) and the calibrator as an 8 V dc loop supply (Figure 7).',
                        steps=common([('Calibrator', 'The 5522A supplies 8 V dc (the program sets it); its value is not critical (printed p. 19).'), ('Meter', 'External DMM in dc current in the loop.'),
                                      ('UUT', 'mA Source function, Simulate Transmitter, 4 mA then 22 mA (the table points are 4 mA and 21 mA, printed p. 20).')]),
                        caution='8 V dc is applied to the loop. Keep the calibrator in STANDBY while you change the connections.', diagram='diagrams/hook_fluke753_SRC_SIM.png'),
        'SRC_OHM': dict(title='Change the cables: UUT sources resistance / RTD', summary='UUT SOURCE jacks, both HI on the VOhm RTD jack and both LO on the jack below it (two wires at the UUT) -> external DMM four-wire ohms (Figure 8).',
                        steps=common([('Meter', 'External DMM in four-wire ohms: 200 ohm range for the first five resistance points, autorange after (printed p. 20); RTD source: four-wire ohms autorange (printed p. 29).'),
                                      ('UUT', 'Resistance source at 0.1 ohm (RTD source: Pt100 (385) at -180 C, ITS-90). Push CLEAR twice at the end.')]),
                        caution=None, diagram='diagrams/hook_fluke753_SRC_OHM.png'),
        'SRC_FREQ': dict(title='Change the cables: UUT sources frequency', summary='UUT SOURCE jacks -> BNC adapter -> frequency counter (Tektronix FCA3000) and the Fluke 123 channel A (Figure 9).',
                         steps=common([('Meter', 'Frequency counter on the UUT output; the Fluke 123 (channel A, BNC input) shows the waveform (printed pp. 21-22).'),
                                       ('UUT', 'Source, frequency, 1.000 Vpp, square wave, 5 Hz first (printed p. 21); the sine points follow Table 12 order; push CLEAR twice at the end.')]),
                         caution=None, diagram='diagrams/hook_fluke753_SRC_FREQ.png'),
        'SRC_TC': dict(title='Change the cables: UUT sources a thermocouple (Type K)', summary='Type K wire from the UUT TC jack through copper / Type K junctions in the lag bath to the external DMM (Figure 10, DMM in place of the 5522A).',
                       steps=common([('Meter', 'External DMM in dc millivolts. Type K to copper junctions welded or in tight screw terminals, in the lag bath at room temperature; measure the bath with the standard thermometer (printed p. 25).'),
                                     ('UUT', 'Thermocouple source, linear mode, Type K, ITS-90, internal reference, degC. Wait 1 minute for thermal emfs and 15 minutes for the bath.')]),
                       caution=None, diagram='diagrams/hook_fluke753_SRC_TC.png'),
        'LOOP': dict(title='Change the cables: loop power', summary='UUT mA jack and common -> external DMM INPUT HI / LO (Figure 13).',
                     steps=common([('Meter', 'External DMM in dc volts.'), ('UUT', 'SETUP, ENTER, select Loop Power, ENTER. When complete, disable Loop Power in the setup menu or turn the UUT off (printed p. 30).')]),
                     caution=None, diagram='diagrams/hook_fluke753_LOOP.png'),
        'HART': dict(title='Change the cables: HART mode (754 only)', summary='UUT mA jack and common -> HART transmitter (Figure 15).',
                     steps=common([('UUT', 'SETUP, HART Channel, ENTER, select mA Jack, ENTER. Connect to the HART transmitter as Figure 15, push HART (enable Loop Power if needed). The Active Device screen must show the transmitter (printed p. 31).')]),
                     caution=None, diagram='diagrams/hook_fluke753_HART.png'),
    }


SOURCE_NOTE = (
    'Fluke 753/754 Calibration Manual, Performance Verification Tests, printed pp. 9-32 (16 tables: 8 measure, 7 source, loop power; plus the 754-only HART check). '
    'The UUT is itself a calibrator: where it MEASURES (Tables 3-7, 13, 15, 16) the lab calibrator sources the value and the display is typed; where it SOURCES (Tables 8-12, 14, 17, loop power) the reading is '
    'MANUAL ENTRY of the external meter (the manual: Fluke 8508A DMM, Tektronix FCA3000 counter). 1-year limits are used; 2-year limits are stored in the spec. '
    'The only thermocouple type the manual verifies is Type K. Table 3 row 30 V prints a 1-year maximum of 29.9870 (misprint): 30.0065 is used.')
REPORT_NOTE = (
    'Limits: Fluke 753/754 Calibration Manual, Performance Verification Tests (1-year column), unchanged except the 30 V dc row of Table 3 (printed maximum 29.9870, a misprint; 30.0065 used). '
    'Points marked (UUT input) were sourced by the calibrator named in the standards used; points marked (UUT output) were read on an external measuring instrument and typed in, '
    'and their Uncertainty is that of the measuring standard named in the row. Thermocouple points are Type K.')


def check_counts(steps):
    counts = {m: sum(1 for s in steps if m in s['models']) for m in MODELS}
    if counts != EXPECTED:
        raise SystemExit(f'points per model {counts} differ from the expected {EXPECTED}')
    ids = [s['id'] for s in steps]
    if len(set(ids)) != len(ids):
        raise SystemExit('duplicate ids')
    return counts


def build_spec():
    steps = build_steps()
    check_counts(steps)
    return dict(
        schema=3, kind='manual-reading',
        options=dict(hv_threshold_v=30, hv_once_per_group=True, auto_ramp=False, function_prompt=True, report_title='Calibration Data', default_period='1y', hookup_meter='fluke753',
                     uncertainty_standards=dict(default='3458A', choices=['3458A', '34461A', '34465A'], note='measuring standards for the points where the UUT sources (manual entry); a model whose sheet is not installed is left out of the list')),
        source=dict(document=DOCUMENT, pages='9-31 (printed): Tables 2-17, loop power, HART (PDF pages 17-40); specifications pp. 5-8 (PDF 13-16)',
                    cite='Fluke 753/754 Calibration Manual, Performance Verification Tests, printed pp. 9-32; 1-year limits',
                    limits='Manufacturer limits, 1-year column, as printed (one misprint corrected, flagged)', report_note=REPORT_NOTE, note=SOURCE_NOTE),
        models={'753': dict(name='Fluke 753 Documenting Process Calibrator', brand='Fluke', model_note='Fluke 753: 90 points (no HART)'),
                '754': dict(name='Fluke 754 Documenting Process Calibrator', brand='Fluke', model_note='Fluke 754: 91 points (adds the HART mode check)')},
        groups=groups(), steps=steps)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    by = {}
    for s in spec['steps']:
        by[s['section']] = by.get(s['section'], 0) + 1
    print('wrote', OUT.name, len(spec['steps']), 'steps')
    for k, v in by.items():
        print(f'  {k}: {v}')
    flagged = [(s['id'], s['check']['arithmetic']) for s in spec['steps'] if (s.get('check') or {}).get('arithmetic')]
    print('arithmetic disagreements:', len(flagged))
    for i, p in flagged:
        print('  ', i, p)


if __name__ == '__main__':
    main()
