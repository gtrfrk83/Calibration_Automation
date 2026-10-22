"""Builds specs/fluke_87v_pv.json for the shared handheld engine (handheld_dmm.py) from the Fluke 87 Series V Cal Processor MDD.

    python3 specs/build_87v_spec.py ["path to the 87V .MDD"]

Every limit (low / high), nominal and unit is taken from the MDD as it is printed. What the MDD does not say (calibrator
output kind, wiring group, which meter mode to select) is added here and shown to the technician as a note.
Rows that have a numeric range but no input signal (open capacitance, 0 nS) are numeric points with no calibrator output.
"""
from __future__ import annotations

import json
import re
import sys
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from mdd_importer_v49 import parse_mdd   # noqa: E402

SAMPLE = 'Fluke 87 Series V Multimeter, Digital - Handheld (365 Days).MDD'
OUT = HERE / 'fluke_87v_pv.json'

# unit text in the MDD -> (display unit, factor to base unit, base unit)
UNITS = {'mV': ('mV', '0.001', 'V'), 'V': ('V', '1', 'V'), 'Vpp': ('Vpp', '1', 'V'),
         'kHz': ('kHz', '1000', 'Hz'), 'Hz': ('Hz', '1', 'Hz'), '%': ('%', '1', '%'),
         'Ohm': ('Ω', '1', 'ohm'), 'kOhm': ('kΩ', '1000', 'ohm'), 'MOhm': ('MΩ', '1000000', 'ohm'),
         'nS': ('nS', '0.000000001', 'S'), 'A': ('A', '1', 'A'), 'mA': ('mA', '0.001', 'A'), 'µA': ('µA', '0.000001', 'A'),
         'nF': ('nF', '0.000000001', 'F'), 'µF': ('µF', '0.000001', 'F'), '°F': ('°F', '1', 'degF')}


def f_to_c(text):
    """Exact (F - 32) * 5 / 9 of a printed °F number, as a one-decimal string ('30.2' -> '-1.0', '212' -> '100.0')."""
    c = (D(text) - 32) * 5 / 9
    q = c.quantize(D('0.1'))
    assert q == c, f'{text} °F is not an exact one-decimal °C value'
    return str(q)

# per MDD row number: (section, switch, range, kind, extra)
# kind: ACV DCV ACI DCI OHM CAP TEMP, DUTY / SQUARE (square-wave source: applied = value in V peak-to-peak, frequency, duty %, DC offset V), or NONE
# (numeric reading with no calibrator output)
ROWS = {}


def rows(first, last, section, switch, ranges, kind, **extra):
    for i, n in enumerate(range(first, last + 1)):
        rng = ranges[i] if isinstance(ranges, list) else ranges
        ROWS[n] = (section, switch, rng, kind, extra)


ACV_SW, DCV_SW = 'V~  (AC volts)', 'V⎓  (DC volts)'
for n, rng in zip(range(1, 11), ['600 mV', '600 mV', '6 V', '6 V', '60 V', '60 V', '600 V', '600 V', '1000 V', '1000 V']):
    ROWS[n] = ('AC volts', 'mV  (AC millivolts)' if rng == '600 mV' else ACV_SW, rng, 'ACV', {})
rows(11, 12, 'AC volts frequency', 'Hz  (frequency, AC volts input)', '600 mV', 'ACV', note='The meter displays FREQUENCY on this step (the calibrator applies the voltage shown at that frequency).')
rows(13, 13, 'AC volts frequency sensitivity', 'Hz  (frequency, AC volts input)', '6 V', 'ACV', note='The meter displays FREQUENCY on this step.')
rows(14, 14, 'AC volts frequency sensitivity', 'Hz  (frequency, AC volts input)', '60 V', 'ACV', note='The meter displays FREQUENCY on this step.')
rows(15, 15, 'DC volts frequency trigger level', 'Hz  (frequency, DC volts input)', '', 'NONE',
     setup='Set the calibrator or a function generator to 3.4 Vpp at 1000 Hz and connect it to the meter VΩ and COM inputs (this step has no automatic calibrator output). Select the DC volts frequency (Hz) function.')
# Duty cycle: the calibrator sources the square wave (87 Series V Calibration Manual Table 3 step 16, p. 9: 5 V, 1 kHz, DC offset 2.5 V Sq. Wave).
# 5 V is peak-to-peak (5522A Operators Manual p. 4-42); the meter shows the duty cycle in %.
rows(16, 16, 'DC volts duty cycle', 'Hz  (duty cycle, DC volts input)', '6 V', 'DUTY',
     square=dict(value=5.0, frequency=1000.0, duty=50.0, offset=2.5),
     note='The meter displays DUTY CYCLE (%) on this step. The calibrator applies a 5 V p-p square wave, 1 kHz, 2.5 V DC offset, 50 % duty (manual Table 3 step 16, p. 9).')
for n, rng in zip(range(17, 23), ['6 V', '60 V', '600 V', '1000 V', '600 mV', '600 mV']):
    ROWS[n] = ('DC volts', 'mV  (DC millivolts)' if rng == '600 mV' else DCV_SW, rng, 'DCV', {})
for n, rng in zip(range(23, 29), ['600 Ω', '6 kΩ', '60 kΩ', '600 kΩ', '6 MΩ', '60 MΩ']):
    ROWS[n] = ('Resistance', 'Ω  (resistance)', rng, 'OHM', {})
ROWS[29] = ('Conductance', 'nS  (conductance)', '60 nS', 'NONE',
            dict(setup='Leave the meter inputs OPEN (no leads connected to the calibrator) and select conductance (nS). The calibrator stays in STANDBY.'))
ROWS[30] = ('Conductance', 'nS  (conductance)', '60 nS', 'OHM',
            dict(applied=(D('100000000'), None), note='10 nS is a 100 MΩ resistance; the calibrator is set to 100 MΩ. Select conductance (nS) on the meter.', no_uncertainty=True))
ROWS[31] = ('Diode test', 'Diode test', '', 'DCV', {})
ROWS[32] = ('AC current', 'A~  (AC amps)', '6 A', 'ACI', dict(group='AMP10', settle=5))
ROWS[33] = ('DC current', 'A⎓  (DC amps)', '6 A', 'DCI', dict(group='AMP10', settle=5))
ROWS[34] = ('DC current', 'A⎓  (DC amps)', '10 A', 'DCI', dict(group='AMP10', settle=5))
for n, rng, kind in ((35, '60 mA', 'ACI'), (36, '600 mA', 'ACI'), (37, '60 mA', 'DCI'), (38, '600 mA', 'DCI'),
                     (39, '600 µA', 'ACI'), (40, '6000 µA', 'ACI'), (41, '600 µA', 'DCI'), (42, '6000 µA', 'DCI')):
    ROWS[n] = ('AC current' if kind == 'ACI' else 'DC current', 'mA / µA', rng, kind, dict(group='UAMP'))
ROWS[43] = ('Capacitance', 'Capacitance', '10 nF', 'NONE',
            dict(setup='Remove the test leads / calibrator connections from the meter and leave the capacitance input OPEN. Select capacitance and the 10 nF range. The calibrator stays in STANDBY.'))
ROWS[44] = ('Capacitance', 'Capacitance', '100 nF', 'CAP', dict(settle=10))
ROWS[45] = ('Capacitance', 'Capacitance', '100 µF', 'CAP', dict(settle=15))
LPF = 'Enable the meter low-pass filter mode on the AC volts function for this step (see the 87V manual).'
ROWS[46] = ('Low pass filter', ACV_SW, '', 'ACV', dict(note=LPF))
ROWS[47] = ('Low pass filter', ACV_SW, '', 'ACV', dict(note=LPF))
# Peak Min/Max (87 Series V Calibration Manual Table 3 step 47, p. 11): 6 V dc range, calibrator 6 Vpp, 2 kHz Sq. Wave, DC offset 1 V, so the signal swings
# +4 V / -2 V; Max = 3.897 to 4.103 V, Min = -1.898 to -2.102 V (87 column). Both points use the SAME square wave; the meter is read in DC volts.
# The MDD's MAX row (source +6 V DC, 5.896 to 6.104 V) does not match the manual: the manual's source and Max limits are used (the MIN row is identical).
# The indicator 'p' = Peak Min Max mode, response time 250 us (display feature table); the manual does not say which key enters it.
PEAK_SQ = dict(value=6.0, frequency=2000.0, duty=50.0, offset=1.0)
ROWS[48] = ('Peak Min / Max', DCV_SW, '6 V', 'SQUARE', dict(
    square=PEAK_SQ, limits=('3.897', '4.103'), nominal=4.0,
    prompt='With the meter on V DC (6 V range), select Peak Min Max (the p indicator shows the 250 µs Peak Min Max mode), then read MAX.',
    note='Peak Min/Max, read the MAX value. Calibrator: 6 V p-p square wave, 2 kHz, 1 V DC offset, so the signal swings +4 V / -2 V (manual Table 3 step 47, p. 11).'))
ROWS[49] = ('Peak Min / Max', DCV_SW, '6 V', 'SQUARE', dict(
    square=PEAK_SQ,
    prompt='Peak Min Max is on: step the meter to MIN (the display shows MIN) and read it.',
    note='Peak Min/Max, read the MIN value (same 6 V p-p, 2 kHz, 1 V offset square wave; manual Table 3 step 47, p. 11). '
         'After you record this reading, exit Min Max by pressing and holding the MIN MAX button (manual p. 9, pushbutton test step 3).'))
# The MDD prints the temperature limits in °F. The meter is set to °C and the calibrator sources °C. Limits follow the 87 Series V Calibration
# Manual (Table 3 steps 49 / 50, printed p. 11): -1.0 to 1.0 °C at 0 °C and 98.0 to 102.0 °C at 100 °C (lab owner decision; the MDD-derived 99.0 / 101.0 are not used).
TEMP_NOTE = ('Connect the K-type thermocouple between the meter and the calibrator (80AK adapter); allow the junctions to stabilise. '
             'The meter shows °C (set the meter to °C); the calibrator is set in °C.')
ROWS[50] = ('Temperature', 'Temperature', 'Type K', 'TEMP', dict(group='TEMP', settle=30, celsius=0.0,
            note=TEMP_NOTE))
ROWS[51] = ('Temperature', 'Temperature', 'Type K', 'TEMP', dict(group='TEMP', settle=30, celsius=100.0,
            note=TEMP_NOTE))


def number(text):
    return D(text)


def clean(value: D) -> float:
    return float(f'{float(value):.9g}')


def parse_nominal(point):
    """(value text, unit, condition text) from the MDD nominal cell, e.g. '330.0 mV~@ 60 Hz'."""
    first, _, cond = (point.get('Text_Nominal') or '').partition('~')
    first = re.sub(r'\s+', ' ', first).strip()
    cond = re.sub(r'\s+', ' ', cond.replace('~', ' ')).strip()
    m = re.match(r'^([-+]?\d+(?:\.\d+)?(?:\s+to\s+[-+]?\d+(?:\.\d+)?)?)\s*(\S*)$', first)
    return m.group(1), m.group(2), cond


def build(mdd: Path):
    parsed = parse_mdd(mdd)
    steps = []
    for n, p in enumerate(parsed['points'], 1):
        section, switch, rng, kind, extra = ROWS[n]
        nominal_text, nominal_unit, cond = parse_nominal(p)
        pass_fail = (p.get('Text_Tolerance') or '').strip().lower().startswith('pass/fail')
        if pass_fail:                                # the printed limits are in the nominal cell ("0.21 to 31 nF")
            low, high = [t.strip() for t in nominal_text.split(' to ')]
            tol_unit = nominal_unit
        else:
            tol_unit = re.sub(r'\[.*?\]', '', (p.get('Text_Tolerance') or '').split('~')[0]).split()[-1]
            low, high = p['Tol_Low'].strip(), p['Tol_High'].strip()
        display, factor, base = UNITS[tol_unit]
        if kind == 'TEMP':                           # the meter is set to °C: limits and nominal are the exact conversions of the printed °F values
            assert tol_unit == '°F'
            display, factor, base = '°C', '1', 'degC'
            low, high, nominal_text = f_to_c(low), f_to_c(high), f_to_c(nominal_text)
        if 'limits' in extra:                        # manual-derived limits (peak Min/Max MAX)
            low, high = extra['limits']
        if 'nominal' in extra:
            nominal_text = str(extra['nominal'])
        step = dict(table='1', step=n, section=section, switch=switch, range=rng, models=['87V'], kind=kind, display_unit=display,
                    factor=float(D(factor)), base_unit=base, low=low, high=high, test='numeric')
        # what the calibrator applies
        m_f = re.search(r'@\s*([\d.]+)\s*(kHz|Hz)', cond)
        freq = float(D(m_f.group(1)) * (1000 if m_f.group(2) == 'kHz' else 1)) if m_f else None
        reading_is_frequency = display in ('kHz', 'Hz', '%')
        if kind == 'NONE':
            step['nominal'] = clean(D(nominal_text) * D(factor)) if 'to' not in nominal_text else 0.0
            step['setup_key'] = 'NONE'
        elif 'applied' in extra:
            value, f = extra['applied']
            step['applied'] = dict(value=clean(value), frequency=f)
            step['nominal'] = clean(D(nominal_text) * D(factor))
        elif 'square' in extra:                       # square-wave source (duty cycle, peak Min/Max)
            step['applied'] = dict(extra['square'])
            step['nominal'] = clean(D(nominal_text) * D(factor))
        elif kind == 'TEMP':
            step['applied'] = dict(value=extra['celsius'], frequency=None)
            step['nominal'] = clean(D(nominal_text) * D(factor))
            assert step['nominal'] == extra['celsius'], 'nominal °C must equal the calibrator output'
        elif reading_is_frequency:                    # frequency reading: the voltage is in the condition, the frequency is the nominal
            m_v = re.search(r'@\s*([\d.]+)\s*(mV|V)', cond)
            volts = D(m_v.group(1)) * (D('0.001') if m_v.group(2) == 'mV' else 1)
            step['applied'] = dict(value=clean(volts), frequency=clean(D(nominal_text) * D(factor)))
            step['nominal'] = clean(D(nominal_text) * D(factor))
        elif 'to' in nominal_text:                    # limits printed as the nominal (low-pass filter rows): apply the voltage named in the function
            volts = {46: 400, 47: 400}[n]
            step['applied'] = dict(value=float(volts), frequency={46: 400.0, 47: 800.0}[n])
            step['nominal'] = float(volts)
        else:
            value = D(nominal_text) * D(factor)
            step['applied'] = dict(value=clean(value), frequency=freq if kind in ('ACV', 'ACI') else None)
            step['nominal'] = clean(value)
        if n in (46, 47):
            step['section'] = 'Low pass filter'
            step['range'] = f'400 V @ {int(step["applied"]["frequency"])} Hz'
            step['nominal'] = 400.0
        for key in ('note', 'setup', 'group', 'settle', 'no_uncertainty', 'prompt'):
            if key in extra:
                step[key] = extra[key]
        if kind == 'NONE' and n == 43:
            step['display_unit'], step['factor'], step['base_unit'] = 'nF', 1e-09, 'F'
        step['id'] = f'1-{n}'
        steps.append(step)
    h = parsed['header']
    return dict(
        schema=2, kind='manual-reading',
        options=dict(hookup_meter='fluke87v', hv_threshold_v=60, auto_ramp=False, function_prompt=True),
        source=dict(document='Fluke 87 Series V Multimeter - Cal Processor datasheet ' + (h.get('Procedure_Name') or 'ATS-1040').strip() + ' (365 days)',
                    pages='MDD points 1-51', cite='Fluke 87 Series V calibration datasheet (MDD), 365 day interval',
                    limits='Limits as printed in the MDD datasheet (365 day)',
                    note='Limits are the MDD datasheet limits. Capacitance (open) and the two low-pass-filter rows are printed as Pass/Fail with a numeric range; '
                         'they are recorded here as numeric readings against that range. Calibrator: Fluke 5560A or 5522A.'
                         " Duty cycle (1-16) and Peak Min/Max (1-48, 1-49) are sourced as square waves per the 87 Series V Calibration Manual Table 3 (printed pp. 9 and 11); "
                         "the Peak Min/Max MAX limits are the manual's (the MDD printed a 6 V DC source). Temperature limits are the exact degC conversions of the MDD's degF limits."),
        models={'87V': dict(name='Fluke 87V', brand='Fluke', model_note='Fluke 87 Series V true-rms digital multimeter')},
        steps=steps)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    candidates = [Path(arg)] if arg else [ROOT / SAMPLE, ROOT.parent / SAMPLE, ROOT / 'Procedures' / SAMPLE]
    mdd = next((c for c in candidates if c.is_file()), None)
    if mdd is None:
        raise SystemExit('87V MDD not found; pass its path as the first argument')
    spec = build(mdd)
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
    print('wrote', OUT, len(spec['steps']), 'points')


if __name__ == '__main__':
    main()
