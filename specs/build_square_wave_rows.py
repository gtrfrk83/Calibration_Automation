"""Writes the square-wave rows (amplitude, DC offset, duty cycle) of the Fluke 5522A, 5520A and 5560A standard sheets (specs/standards/fluke_*_standard.json).

    python specs/build_square_wave_rows.py         # the 5522A sheet (it has no builder of its own)
    python specs/build_5520a_standard.py / build_5560a_standard_from_manual.py   # these call functions_5520a / functions_5560a

Idempotent: the square-wave functions are replaced on every run; every other row of a sheet is untouched.
They give the square-wave points of the handheld procedures (Fluke 83V / 87V / 88V duty cycle 3-16 and Peak Min/Max 3-47) an uncertainty from the
calibrator's published specification (owner decision 2026-10-28: calibrator specification, no flag; the lab's A2LA scope has no square-wave line).

Every number was read from RENDERED PAGE IMAGES (pypdfium2, 2.5x), twice:
  5522A  '5522 manual.pdf' (Operators Manual). Printed 1-23 (PDF 43) "AC Voltage (Non-Sine Wave)", Square Wave, Normal Channel: four p-p ranges
         (2.9 to 65.999 mV, 66 to 659.999 mV, 0.66 to 6.59999 V, 6.6 to 66.0000 V) x five bands, +/-(% of output + % of range), 1-Year column only.
         'Range' is the p-p range the output falls in (66 mV, 660 mV, 6.6 V, 66 V): the earlier sheet used 66 Vpp for every output (corrected here).
         Printed 1-24 (PDF 44) "AC Voltage, DC Offset", Square Waves (p-p): +/-(0.1 % of dc output + floor 66 uV / 660 uV / 6600 uV / 66 mV); footnote 3: 0.01 Hz to 10 Hz
         and 500 kHz to 2 MHz differ (not stored). Same page, "Square Wave Characteristics": duty cycle +/-(0.02 % of period + 100 ns) at 50 %, +/-(0.05 % of period + 100 ns)
         from 10 % to 90 %; duty range "1 % to 99 % <3.3 V p-p, 0.01 Hz to 100 kHz". Confidence 99 % (printed 1-8).
  5520A  '5520A Manual.pdf' (Service Manual). Printed 1-26 (PDF 42) "AC Voltage (Non-Sine Wave)", Square Wave, Normal Channel: ONE amplitude row '2.9 mV to 66 V' x five bands,
         +/-(% of output + % of range); the table defines no other range, so the range term is 66 Vpp (as printed; the conservative reading). Printed 1-27 (PDF 43) DC offset, as the 5522A
         (the manual prints the last two range starts as '0.66 mV' and '6.6 mV': typos for 0.66 V / 6.6 V). Printed 1-28 (PDF 44) duty cycle, as the 5522A. Confidence 99 % (printed 1-7).
  5560A  '5560 Specs.pdf' (Product Specifications). Printed 24 (PDF 25) "ACV Square Wave Specifications +/-(% Output + Floor)": ranges 12 mV / 120 mV / 1.2 V / 12 V / 120 V
         (Max Vpp 22 mV / 220 mV / 2.2 V / 22 V / 66 V) x five bands; the 95 % columns are stored (this sheet is the 95 % one, divisor 2). Printed 26 (PDF 27) "ACV DC Offset":
         0.10 % + floor 12 uV / 120 uV / 1.2 mV / 120 mV / 1.2 V (the 12 V floor is printed 120 mV, out of the decade pattern: stored as printed, flagged); DC offset available
         above 40 Hz. Duty cycle: printed 24 (PDF 25), the existing 'Frequency [Duty Cycle]' rows (0.03 / 0.06 %DC at 1000 Hz) are already this specification; not rewritten here.
Duty cycle (5522A / 5520A): '% of period + 100 ns' is a time; it is stored as %DC AT 1000 Hz only (period 1 ms: 0.02 % + 100 ns = 0.03 %DC, 0.05 % + 100 ns = 0.06 %DC), the
same form the 5560A sheet uses. Another frequency needs its own row.
The 1-Year figures are stored for both periods the sheets use ('90 day' and '1 yr'): the 5522A / 5520A non-sine tables print a 1-Year column only.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent / 'standards'
BANDS = ((0.01, 10.0), (10.0, 45.0), (45.0, 1000.0), (1000.0, 20000.0), (20000.0, 100000.0))
AMP = 'Voltage, AC [Squarewave (Normal Output)]'
OFFSET = 'Voltage, AC [Squarewave DC Offset (Normal Output)]'
DUTY = 'Frequency [Duty Cycle]'


def fmt(v, unit):
    return f'{v:g} {unit}'


def spec(periods, raw, rel=0.0, fs_rel=0.0, fs_value=0.0, abs_=0.0, unit='Vpp'):
    return [dict(period=p, rel=rel, fs_rel=fs_rel, fs_value=fs_value, abs=abs_, unit=unit, le=False, raw=f'[{p}] Accuracy: {raw}') for p in periods]


def row(label, page, params, specs, kind, variant, amp, unit, freq=None, qualifiers=()):
    return dict(label=label, page=page, params=params, specs=specs, raw_other=[], kind=kind, variant=variant, amp_lo=amp[0], amp_hi=amp[1], unit=unit,
                freq_lo=freq[0] if freq else None, freq_hi=freq[1] if freq else None, qualifiers=list(qualifiers), range_max=None, resolution=None, res_src='')


def param(lo, hi, unit, tag=''):
    text = (f'[{tag}] ' if tag else '') + f'{lo:g} {unit} to {hi:g} {unit}'
    return dict(tag=tag, lo=lo, hi=hi, unit=unit, text=text, annot='', notes=[])


# ------------------------------------------------------------------------------------------------ amplitude
FLUKE_552X_PCT = ((5.0, 0.5), (0.25, 0.5), (0.25, 0.25), (0.5, 0.25), (5.0, 0.5))     # +/-(% of output, % of range) per band (5522A p. 1-23, 5520A p. 1-26)


def amp_552x(ranges, page, periods):
    out = []
    for lo, hi, fs in ranges:
        for (flo, fhi), (pct, pct_r) in zip(BANDS, FLUKE_552X_PCT):
            raw = f'+/-({pct:g}% I.V. + {pct_r:g}% F.S.{{"Full Scale" = {fs:g} Vpp}})'
            out.append(row(f'{fmt(lo, "Vpp")} to {fmt(hi, "Vpp")}, {fmt(flo, "Hz")} to {fmt(fhi, "Hz")}', page, [param(lo, hi, 'Vpp'), param(flo, fhi, 'Hz')],
                           spec(periods, raw, rel=pct / 100, fs_rel=pct_r / 100, fs_value=fs), 'ACV', 'Squarewave (Normal Output)', (lo, hi), 'Vpp', (flo, fhi)))
    return out


R_5522A = ((0.0029, 0.065999, 0.066), (0.066, 0.659999, 0.66), (0.66, 6.59999, 6.6), (6.6, 66.0, 66.0))
R_5520A = ((0.0029, 66.0, 66.0),)
# 5560A: (range low, Max Vpp, floor per band in Vpp); the 95 % percentages per band
R_5560A = ((0.002, 0.022, (110e-6, 110e-6, 55e-6, 55e-6, 110e-6)), (0.022, 0.22, (1.1e-3, 1.1e-3, 0.55e-3, 0.55e-3, 1.1e-3)),
           (0.22, 2.2, (11e-3, 11e-3, 5.5e-3, 5.5e-3, 11e-3)), (2.2, 22.0, (110e-3, 110e-3, 55e-3, 55e-3, 110e-3)), (22.0, 66.0, (1.1, 1.1, 0.55, 0.55, 1.1)))
PCT_5560A_95 = (3.9, 0.20, 0.20, 0.40, 3.9)


def amp_5560a(periods):
    out = []
    for lo, hi, floors in R_5560A:
        for (flo, fhi), pct, floor in zip(BANDS, PCT_5560A_95, floors):
            raw = f'+/-({pct:g}% I.V. + {floor:g} Vpp)'
            out.append(row(f'{fmt(lo, "Vpp")} to {fmt(hi, "Vpp")}, {fmt(flo, "Hz")} to {fmt(fhi, "Hz")}', 24, [param(lo, hi, 'Vpp'), param(flo, fhi, 'Hz')],
                           spec(periods, raw, rel=pct / 100, abs_=floor), 'ACV', 'Squarewave (Normal Output)', (lo, hi), 'Vpp', (flo, fhi)))
    return out


# ------------------------------------------------------------------------------------------------ DC offset (amplitude of the row = the offset, V; qualifier 'Vpp' = the square-wave range)
OFF_552X = ((0.0066, 0.065999, 0.05, 66e-6), (0.066, 0.659999, 0.5, 660e-6), (0.66, 6.59999, 5.0, 6600e-6), (6.6, 66.0, 50.0, 66e-3))
OFF_5560A = ((0.002, 0.022, 0.0085, 12e-6), (0.022, 0.22, 0.085, 120e-6), (0.22, 2.2, 0.85, 1.2e-3), (2.2, 22.0, 8.5, 120e-3), (22.0, 66.0, 85.0, 1.2))


def offset_rows(table, page, periods, band):
    out = []
    for lo, hi, dc_max, floor in table:
        raw = f'+/-(0.1% I.V. + {floor:g} V)'
        out.append(row(f'offset 0 V to {fmt(dc_max, "V")} with {fmt(lo, "Vpp")} to {fmt(hi, "Vpp")}', page,
                       [param(0.0, dc_max, 'V'), param(band[0], band[1], 'Hz'), param(lo, hi, 'Vpp', tag='Vpp')],
                       spec(periods, raw, rel=0.001, abs_=floor, unit='V'), 'ACV', 'Squarewave DC Offset (Normal Output)', (0.0, dc_max), 'V', band,
                       [dict(tag='Vpp', lo=lo, hi=hi, unit='Vpp')]))
    return out


# ------------------------------------------------------------------------------------------------ duty cycle at 1000 Hz (5522A / 5520A)
def duty_rows(page, periods):
    out = []
    for lo, hi, acc, text in ((50.0, 50.0, 0.03, '0.02 % of period + 100 ns at 50 %'), (10.0, 49.0, 0.06, '0.05 % of period + 100 ns, 10 % to 90 %'),
                              (51.0, 90.0, 0.06, '0.05 % of period + 100 ns, 10 % to 90 %')):
        raw = f'+/-({acc:g} %DC)'
        r = row(f'1000Hz {lo:g} to {hi:g} %', page, [param(lo, hi, '%DC'), param(1000.0, 1000.0, 'Hz', tag='Hz')],
                spec(periods, raw, abs_=acc, unit='%DC'), 'FREQ', 'Duty Cycle', (lo, hi), '%DC', None, [dict(tag='Hz', lo=1000.0, hi=1000.0, unit='Hz')])
        r['params'][0]['notes'] = []
        r['raw_other'] = [f'manual: +/-({text}); at 1000 Hz (period 1 ms) = +/-{acc:g} % of the period = {acc:g} %DC']
        out.append(r)
    return out


SQ_NOTE = ('SQUARE WAVE ROWS (amplitude, DC offset, duty cycle at 1 kHz): written by specs/build_square_wave_rows.py from the rendered page images; see that file for the pages. '
           'Used for the uncertainty of square-wave points (Fluke 83V / 87V / 88V duty cycle and Peak Min/Max).')
NOTE_5522A = (SQ_NOTE + ' The amplitude range term is the p-p range of the output (66 mV / 660 mV / 6.6 V / 66 V, printed p. 1-23); the earlier sheet used 66 Vpp for every output. '
              'Duty cycle is specified for 1 % to 99 % below 3.3 V p-p (printed p. 1-24); the 50 % figure is used at higher amplitudes (UNVERIFIED).')
NOTE_5520A = (SQ_NOTE + ' The amplitude table prints one row (2.9 mV to 66 V p-p), so the range term is 66 Vpp. Duty cycle is specified for 1 % to 99 % below 3.3 V p-p (printed p. 1-28); '
              'the 50 % figure is used at higher amplitudes (UNVERIFIED). The WAVE / DUTY / DC_OFFSET commands are not in this Service Manual (UNVERIFIED for the 5520A).')
NOTE_5560A = (SQ_NOTE + ' 95 % columns. The DC offset floor of the 12 V range is printed 120 mV (the other ranges follow 0.1 % of the range): stored as printed, possibly a misprint for 12 mV. '
              'Duty cycle: the Frequency [Duty Cycle] rows (printed p. 24).')
AMP_OFF = ('90 day', '1 yr')


def functions_5522a():
    return [dict(name=AMP, direction='output', page=43, ranges=amp_552x(R_5522A, 43, AMP_OFF)),
            dict(name=OFFSET, direction='output', page=44, ranges=offset_rows(OFF_552X, 44, AMP_OFF, (10.0, 500000.0))),
            dict(name=DUTY, direction='output', page=44, ranges=duty_rows(44, AMP_OFF))]


def functions_5520a():
    """For specs/build_5520a_standard.py (its frequency functions carry the 1 yr column only)."""
    return [dict(name=AMP, direction='output', page=42, ranges=amp_552x(R_5520A, 42, AMP_OFF)),
            dict(name=OFFSET, direction='output', page=43, ranges=offset_rows(OFF_552X, 43, AMP_OFF, (10.0, 500000.0))),
            dict(name=DUTY, direction='output', page=44, ranges=duty_rows(44, ('1 yr',)))]


def functions_5560a(periods):
    """For specs/build_5560a_standard_from_manual.py (its own Frequency [Duty Cycle] rows stay as they are)."""
    return [dict(name=AMP, direction='output', page=24, ranges=amp_5560a(periods)),
            dict(name=OFFSET, direction='output', page=26, ranges=offset_rows(OFF_5560A, 26, periods, (40.0, 500000.0)))]


def main():
    """The 5522A sheet has no builder of its own: its square-wave functions are replaced here (the 5520A and 5560A builders call functions_5520a / functions_5560a)."""
    path = HERE / 'fluke_5522a_standard.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    new = functions_5522a()
    names = {f['name'] for f in new}
    data['functions'] = [f for f in data['functions'] if f['name'] not in names] + new
    data['notes']['square_wave'] = NOTE_5522A
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print('5522A: square-wave functions written', sum(len(f['ranges']) for f in new), 'rows')


if __name__ == '__main__':
    main()
