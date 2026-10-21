"""Builds specs/tektronix_tds2000c_pv.json from the TDS2000C and TDS1000C-EDU Series Service Manual (077-0446-01), Chapter 4
"Performance Verification" (printed pp. 4-1 to 4-13, Appendix A pp. A-1 to A-4).

Every limit was read from the RENDERED PAGE IMAGES (test record p. 4-2, DC gain table p. 4-4, bandwidth p. 4-5, time base p. 4-6/4-7,
trigger p. 4-7/4-8/4-9/4-10), not from extracted text.

Point fields (base units): section, kind, desc, ch, nominal, low, high (None = one-sided), unit, stim ('cal' = calibrator scope option,
'none' = no input), models (omitted = all), plus per-kind parameters.  Pass/fail points (passfail=True) carry low = high = 1.

Run:  python specs/build_tds2000c_spec.py        (writes next to this script)
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / 'tektronix_tds2000c_pv.json'

# ---- the ten models the chapter covers -------------------------------------------------------------------------------------------
# bw_mhz       : model bandwidth. bw_test_hz : frequency of the analog bandwidth test (p. 4-5 step 7).
# trig_hz      : frequency of the edge-trigger tests (p. 4-8 step 8, p. 4-10 step 7); 200 MHz models also run 200 MHz afterwards.
# The manual prints "TDS2004B" in the bandwidth list (p. 4-5, 70 MHz row) and "TDS2004C" in the trigger lists; TDS2004C is used (TDS2004B
# is not a model this chapter covers).
MODELS = {
    '1001C-EDU': dict(channels=2, bw_mhz=40, bw_test_hz=40e6, trig_hz=40e6),
    '2001C':     dict(channels=2, bw_mhz=50, bw_test_hz=50e6, trig_hz=50e6),
    '1002C-EDU': dict(channels=2, bw_mhz=60, bw_test_hz=60e6, trig_hz=60e6),
    '2002C':     dict(channels=2, bw_mhz=70, bw_test_hz=70e6, trig_hz=70e6),
    '2004C':     dict(channels=4, bw_mhz=70, bw_test_hz=70e6, trig_hz=70e6),
    '1012C-EDU': dict(channels=2, bw_mhz=100, bw_test_hz=100e6, trig_hz=100e6),
    '2012C':     dict(channels=2, bw_mhz=100, bw_test_hz=100e6, trig_hz=100e6),
    '2014C':     dict(channels=4, bw_mhz=100, bw_test_hz=100e6, trig_hz=100e6),
    '2022C':     dict(channels=2, bw_mhz=200, bw_test_hz=200e6, trig_hz=100e6),
    '2024C':     dict(channels=4, bw_mhz=200, bw_test_hz=200e6, trig_hz=100e6),
}
FOUR_CH = [m for m, v in MODELS.items() if v['channels'] == 4]
HZ200 = [m for m, v in MODELS.items() if v['bw_mhz'] == 200]

TITLES = {'selftest': 'Self test and self calibration', 'gain': 'DC gain accuracy', 'bw': 'Analog bandwidth',
          'timebase': 'Sample rate and delay time accuracy', 'trig': 'Edge trigger sensitivity',
          'exttrig': 'External edge trigger sensitivity'}
PAGES = {'selftest': '4-3', 'gain': '4-3', 'bw': '4-5', 'timebase': '4-6', 'trig': '4-7', 'exttrig': '4-9'}
points = []


def add(sec, kind, desc, nominal, low, high, unit, ch=None, models=None, stim='cal', **kw):
    p = dict(section=sec, kind=kind, desc=desc, ch=ch, nominal=nominal, low=low, high=high, unit=unit, stim=stim)
    if models:
        p['models'] = models
    p.update(kw)
    points.append(p)


def f9(x):
    return float(f'{x:.9g}')


def models_for(ch):
    return FOUR_CH if ch > 2 else None


# ---- self test / self calibration (p. 4-3). Not rows of the test record, but required before it ("two conditions must be met") ----
add('selftest', 'SELFTEST', 'Self test (power-on diagnostics, no errors)', 1, 1, 1, '', stim='none', passfail=True,
    note='p. 4-3: "Verify that no error messages are displayed". Read back with DIAg:RESUlt:FLAg?. The scope must have run 20 minutes first.')
add('selftest', 'SELFCAL', 'Self calibration (Utility > Do Self Cal passed)', 1, 1, 1, '', stim='none', passfail=True,
    note='p. 4-3: disconnect all probes and cables first; repeat if the ambient temperature changes by 5 degC or more.')

# ---- DC gain accuracy (p. 4-4; test record p. 4-2) --------------------------------------------------------------------------------
# vscale V/div | +/- source level | Vdiff limits.  Vdiff = Vpos - Vneg.
GAIN = [(5e-3, 17.5e-3, 33.6e-3, 36.4e-3), (0.2, 0.7, 1.358, 1.442), (2.0, 7.0, 13.58, 14.42)]
for ch in (1, 2, 3, 4):
    for vs, lvl, lo, hi in GAIN:
        txt = f'{vs * 1e3:g} mV/div' if vs < 1 else f'{vs:g} V/div'
        add('gain', 'GAIN', f'CH{ch} DC gain, {txt}', f9(2 * lvl), lo, hi, 'V', ch=ch, models=models_for(ch),
            vscale=vs, vpos=lvl, vneg=-lvl, vdiff=f9(2 * lvl))

# ---- analog bandwidth (p. 4-5; test record "Channel n Bandwidth": 2.12 V minimum, no maximum) -----------------------------------------
for ch in (1, 2, 3, 4):
    add('bw', 'BW', f'CH{ch} bandwidth: 3 V p-p at 50 kHz reference, Vpk-pk at model frequency', 2.12, 2.12, None, 'V', ch=ch, models=models_for(ch),
        vscale=0.5, ref_hz=50e3, ref_target=3.0, ref_low=2.98, ref_high=3.02, hscale_ref=10e-6, hscale=10e-9,
        note='Reference level is set at 10 us/div (5 cycles of 50 kHz on screen) instead of the manual 10 ms/div so the whole wave is displayed (deviation requested by the lab; the measured Pk-Pk limits are unchanged). Model frequency: 40/50/60/70/100/200 MHz by model (specs models_info). 50 ohm feedthrough termination at the scope input.')

# ---- sample rate and delay time accuracy (p. 4-6 / 4-7) ------------------------------------------------------------------------------
add('timebase', 'TIMEBASE', 'Time base: rising edge of the 10 ms marker at center screen (divisions)', 0.0, -2.0, 2.0, 'div', ch=1,
    period=10e-3, vscale=0.5, hscale_set=1e-3, delay=10e-3, hscale_meas=250e-9,
    note='1 division of displacement = 25 ppm time base error (p. 4-7 note). Edge position measured from the acquired waveform, not by eye.')

# ---- edge trigger sensitivity (p. 4-7 / 4-8 / 4-9; test record: "Stable trigger") ----------------------------------------------------
# Each stage: freq ('10M' = 10 MHz, 'F' = the model's trigger-test frequency, '200M' = 200 MHz), the amplitude as the MEASURED p-p the
# manual asks for ("so that the measured amplitude is approximately ..."), horizontal scale, slope; check = trigger stability is judged.
TRIG_STAGES = [
    dict(step='5-7',   freq='10M',  meas_vpp=0.5,  hscale=25e-9,  slope='RISe', check=True),
    dict(step='8-11',  freq='F',    meas_vpp=0.75, hscale=5e-9,   slope='RISe', check=True),
    dict(step='12',    freq='200M', meas_vpp=1.0,  hscale=5e-9,   slope='RISe', check=True, models=HZ200),
    dict(step='13-15', freq='LAST', meas_vpp='LAST', hscale=2.5e-9, slope='FALL', check=True),
]
for ch in (1, 2, 3, 4):
    add('trig', 'TRIG', f'CH{ch} edge trigger sensitivity (stable trigger)', 1, 1, 1, '', ch=ch, models=models_for(ch), passfail=True,
        vscale=0.5, stages=TRIG_STAGES,
        note='Pass = stable trigger at every stage (engine criteria: trigger state, acquisitions counting, edge position repeatable).')

# ---- external edge trigger sensitivity (p. 4-9 / 4-10) ----------------------------------------------------------------------------------
# src_vpp = the level set on the calibrator (into the power splitter); ch1_vpp = the level wanted on CH1 where the manual asks for it.
EXT_STAGES = [
    dict(step='5-6',   freq='10M',  src_vpp=0.3, hscale=25e-9,  slope='RISe', check=False, note='about 200 mV p-p on CH1'),
    dict(step='7-9',   freq='F',    src_vpp=0.3, hscale=5e-9,   slope='RISe', check=True),
    dict(step='10-11', freq='200M', ch1_vpp=0.35, hscale=5e-9,  slope='RISe', check=False, models=HZ200),
    dict(step='12-13', freq='LAST', src_vpp='LAST', hscale=2.5e-9, slope='RISe', check=True),
    dict(step='14-15', freq='LAST', src_vpp='LAST', hscale=2.5e-9, slope='FALL', check=True),
]
add('exttrig', 'EXTTRIG', 'External edge trigger sensitivity (stable trigger)', 1, 1, 1, '', ch=1, passfail=True,
    vscale=0.1, stages=EXT_STAGES,
    note='CH1 and EXT TRIG both fed from a power splitter, 50 ohm feedthrough terminators on both inputs.')

# Vertical position accuracy (p. 4-10 to 4-13, Appendix A) is intentionally NOT part of this procedure (removed at the lab's request).

for i, p in enumerate(points, 1):
    p['id'] = i

spec = dict(schema=2, manufacturer='Tektronix', model='TDS2000C / TDS1000C-EDU', models=list(MODELS), models_info=MODELS,
            title='TDS2000C and TDS1000C-EDU Series Performance Verification',
            source=dict(document='TDS2000C and TDS1000C-EDU Series Digital Storage Oscilloscopes Service Manual (077-0446-01)',
                        pages='Chapter 4 pp. 4-1 to 4-13, Appendix A pp. A-1 to A-4',
                        note='Limits read from rendered page images. Equipment table p. 4-1 (DC source 17.5 mV to 7 V +/-0.5 %, leveled sine 50 kHz and 200 MHz '
                             '+/-3 %, 10 ms time mark +/-10 ppm) is met here by the calibrator scope option.'),
            sections=[dict(id=s, title=t, page=PAGES[s]) for s, t in TITLES.items()], points=points)
OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
if __name__ == '__main__':
    from collections import Counter
    print(len(points), 'points ->', OUT, dict(Counter(p['section'] for p in points)))
