"""Builds specs/tektronix_tbs2000b_pv.json from the TBS2000B Series Oscilloscope Specification and Performance Verification manual (077-1538-03 Rev D,
September 2024): Model overview p. 10, Performance verification pp. 19-26 (equipment p. 19, test record pp. 20-21, procedures pp. 22-26).

Every limit, nominal, setting and frequency below was read from the RENDERED PAGE IMAGES (pdftoppm -r 110, the procedure steps again at -r 160), twice, not from
extracted text; the limits are recomputed here in Decimal from the published specifications (pp. 11-13) and the build aborts on a disagreement.

Point fields (base units): section, kind, desc, ch, nominal, low, high (None = one-sided), unit, stim ('cal' = calibrator scope option, 'none' = no input),
models (omitted = all), plus per-kind parameters.  Pass/fail points (passfail=True) carry low = high = 1.  `printed` keeps what the manual prints where the
procedure departs from it (always stated in the point's note and in source.deviations).

Run:  python specs/build_tbs2000b_spec.py        (writes next to this script)
"""
import json
from decimal import Decimal as D
from pathlib import Path

OUT = Path(__file__).resolve().parent / 'tektronix_tbs2000b_pv.json'

# ---- the six models (p. 10 'Model overview'; p. 23 step 16 for the bandwidth-test frequency) ----------------------------------------------------------
MODELS = {
    '2072B': dict(channels=2, bw_mhz=70, bw_test_hz=70e6),
    '2074B': dict(channels=4, bw_mhz=70, bw_test_hz=70e6),
    '2102B': dict(channels=2, bw_mhz=100, bw_test_hz=100e6),
    '2104B': dict(channels=4, bw_mhz=100, bw_test_hz=100e6),
    '2202B': dict(channels=2, bw_mhz=200, bw_test_hz=200e6),
    '2204B': dict(channels=4, bw_mhz=200, bw_test_hz=200e6),
}
FOUR_CH = [m for m, v in MODELS.items() if v['channels'] == 4]

TITLES = {'selftest': 'Self test and signal path compensation', 'bw': 'Bandwidth', 'offset': 'Vertical offset accuracy',
          'timebase': 'Sample rate and delay time accuracy', 'dcbal': 'DC balance'}
PAGES = {'selftest': '22', 'bw': '23', 'offset': '24', 'timebase': '25', 'dcbal': '26'}
points = []


def add(sec, kind, desc, nominal, low, high, unit, ch=None, models=None, stim='cal', **kw):
    p = dict(section=sec, kind=kind, desc=desc, ch=ch, nominal=nominal, low=low, high=high, unit=unit, stim=stim)
    if models:
        p['models'] = models
    p.update(kw)
    points.append(p)


def models_for(ch):
    return FOUR_CH if ch > 2 else None


def check(what, printed, computed, tol=D(0)):
    if abs(D(printed) - D(computed)) > tol:
        raise SystemExit(f'{what}: printed {printed} disagrees with the specification ({computed})')


# ---- published specifications used for the cross-check (pp. 11-13) ---------------------------------------------------------------------------------------
def dc_balance(vdiv):                         # p. 11: DC balance +/-(1 mV + 0.1 div)
    return D('0.001') + D('0.1') * D(vdiv)


def offset_accuracy(vdiv, offset, position):   # p. 11: vertical offset accuracy +/-(0.01 x |offset - position| + DC balance), position in volts = div x V/div
    return D('0.01') * abs(D(offset) - D(position) * D(vdiv)) + dc_balance(vdiv)


# ---- self test / signal path compensation (p. 22; test record p. 20 'Self test', 'Signal path compensation (SPC)') -----------------------------------
add('selftest', 'SELFTEST', 'Self test (Utility > Diagnostics > Self Test, 1 loop: passed)', 1, 1, 1, '', stim='none', passfail=True,
    note='p. 22: run from the front panel by the technician (Loop Times 1); the result is read back with DIAg:RESUlt:FLAg?. The scope must have run 20 minutes first.')
add('selftest', 'SPC', 'Signal path compensation (Compensate Signal Paths: passed)', 1, 1, 1, '', stim='none', passfail=True,
    note='p. 22: all probes and cables removed first; repeat if the temperature changes by more than 10 degC. Run remotely with *CAL?, confirmed with CALibrate:RESults:SPC?.')

# ---- bandwidth (p. 23; test record Table 4 p. 20: 2.12 V low limit, no high limit) ------------------------------------------------------------------------
BW_LOW = D('2.12')
check('bandwidth low limit', BW_LOW, (D(3) / D(2).sqrt()).quantize(D('0.01'), rounding='ROUND_DOWN'))      # -3 dB of the 3.00 V reference, truncated as printed
for ch in (1, 2, 3, 4):
    add('bw', 'BW', f'CH{ch} bandwidth: 3 V p-p reference, Vpk-pk at the model frequency', float(BW_LOW), float(BW_LOW), None, 'V', ch=ch, models=models_for(ch),
        vscale=0.5, ref_hz=50e3, ref_target=3.0, ref_low=2.98, ref_high=3.02, hscale_ref=10e-6, hscale=10e-9,
        printed=dict(ref_hz=1e3, hscale_ref=400e-6),
        note='p. 23: 500 mV/div, trigger coupling Noise Reject, source = channel under test, 50 ohm feedthrough terminator. The reference is set at 50 kHz, '
             'not the 1 kHz of step 14: the calibrator leveled sine starts at 50 kHz, which is also the equipment table frequency (p. 19); shown at 10 us/div '
             'instead of 400 us/div so a few cycles fill the screen. Model frequency 70 / 100 / 200 MHz (step 16) at 10 ns/div.')

# ---- vertical offset accuracy (p. 24; test record Table 5 'Vertical position range' pp. 20-21, Pass/Fail) ---------------------------------------------------
# (V/div, trace position div, offset V, DC source V) in the order of the steps 5-27; pass = trace within 0.2 division of the centre line.
OFFSET = [('0.2', -5, '0.8', '1.8'), ('0.2', 5, '-0.8', '-1.8'), ('5', -5, '20', '45'), ('5', 5, '-20', '-45')]
LIMIT_DIV = D('0.2')
for vdiv, pos, off, src in OFFSET:
    shown = D(pos) + (D(src) - D(off)) / D(vdiv)                    # where the trace is displayed (p. 59: input minus offset, at the position)
    check(f'offset {off} V at {vdiv} V/div: trace position', shown, 0)
    spec_div = offset_accuracy(vdiv, off, pos) / D(vdiv)
    check(f'offset {off} V at {vdiv} V/div: 0.2 div against the specification ({spec_div:.3f} div)', LIMIT_DIV, spec_div, tol=D('0.011'))
for ch in (1, 2, 3, 4):
    for vdiv, pos, off, src in OFFSET:
        half = LIMIT_DIV * D(vdiv)
        txt = f'{int(D(vdiv) * 1000)} mV/div' if D(vdiv) < 1 else f'{D(vdiv):g} V/div'
        add('offset', 'OFFSET', f'CH{ch} offset {D(off):+g} V, {txt}, trace at {pos:+d} div: {D(src):+g} V in', float(D(src)), float(D(src) - half),
            float(D(src) + half), 'V', ch=ch, models=models_for(ch), vscale=float(D(vdiv)), position=float(pos), offset=float(D(off)), vsrc=float(D(src)),
            limit_div=float(LIMIT_DIV),
            note=f'p. 24: the trace must be within {LIMIT_DIV} division of the centre line (pass / fail in the test record); recorded as the MEAN the scope '
                 f'measures, limits = source +/- {LIMIT_DIV} div x {txt} = +/- {half:g} V. Specification p. 11: '
                 f'+/-{offset_accuracy(vdiv, off, pos) / D(vdiv):.3f} div here.')

# ---- sample rate and delay time accuracy (p. 25; test record Table 6 p. 21: -2.5 to +2.5 divs) ----------------------------------------------------------
TB_DIV = D('2.5')
check('time base: 2.5 div x 10 ns/div of a 1 ms delay = 25 ppm (p. 13: +/-25 ppm over any >= 1 ms interval)', TB_DIV * D('10e-9') / D('1e-3') * D(10) ** 6, 25)
add('timebase', 'TIMEBASE', 'Time base: rising edge of the 1 ms marker at 1 ms delay, from the centre line (divisions)', 0.0, -float(TB_DIV), float(TB_DIV), 'div',
    ch=1, period=1e-3, vscale=0.5, hscale_set=1e-3, delay=1e-3, hscale_meas=10e-9,
    note='1 division of displacement = 10 ppm time base error (p. 25 note); +/-2.5 div = +/-25 ns. Edge position measured from the acquired waveform, not by eye. '
         'The equipment table (p. 19) lists a 10 ms time mark; the procedure (step 2) uses 1 ms, which is used here.')

# ---- DC balance (p. 26; test record Table 3 p. 20: -21 mV to +21 mV, DC coupling) ---------------------------------------------------------------------------
DCB = D('0.021')
check('DC balance limit at 200 mV/div', DCB, dc_balance('0.2'))
for ch in (1, 2, 3, 4):
    add('dcbal', 'DCBAL', f'CH{ch} DC balance, 200 mV/div, 50 ohm terminated (mean)', 0.0, -float(DCB), float(DCB), 'V', ch=ch, models=models_for(ch), stim='none',
        vscale=0.2, hscale=1e-3, averages=16,
        note='p. 26: no signal, 50 ohm terminator on the input, AC Line trigger, Average 16, 1 ms/div, DC coupling, MEAN measurement.')

for i, p in enumerate(points, 1):
    p['id'] = i

spec = dict(schema=2, manufacturer='Tektronix', model='TBS2000B', models=list(MODELS), models_info=MODELS,
            title='TBS2000B Series Performance Verification',
            source=dict(document='TBS2000B Series Oscilloscope Specification and Performance Verification (077-1538-03 Rev D)',
                        pages='Model overview p. 10, specifications pp. 10-16, performance verification pp. 19-26',
                        note='Limits read from rendered page images and recomputed from the specifications pp. 11-13. Equipment table p. 19 (DC source 17.5 mV to 7 V '
                             '+/-0.5 %, leveled sine 50 kHz and 200 MHz +/-3 %, time mark 10 ms +/-10 ppm) is met here by the calibrator scope option.',
                        deviations=['Bandwidth reference at 50 kHz and 10 us/div instead of 1 kHz and 400 us/div (p. 23 steps 13-14): the calibrator leveled sine '
                                    'starts at 50 kHz (equipment table p. 19 also says 50 kHz).',
                                    'Vertical offset accuracy (pass/fail by eye, p. 24) is recorded as the MEAN voltage the scope measures with limits of the source '
                                    '+/- 0.2 division.',
                                    'Time base edge position is measured from the waveform record instead of by eye (p. 25 step 15).',
                                    'Self test is run from the front panel by the technician (p. 22 steps 3-9) and its result read back remotely.']),
            sections=[dict(id=s, title=t, page=PAGES[s]) for s, t in TITLES.items()], points=points)
OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
if __name__ == '__main__':
    from collections import Counter
    print(len(points), 'points ->', OUT, dict(Counter(p['section'] for p in points)))
