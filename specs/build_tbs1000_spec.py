"""Builds specs/tektronix_tbs1000_pv.json from the TBS1000 Series Digital Storage Oscilloscopes Service Manual (077-0772-01, Revision D,
"applies to TBS1000 models with no display adapter module"), Chapter 4 "Performance Verification" (printed pp. 4-1 to 4-10; the PDF page is
the printed page + 46 in this chapter).  The non-C TBS1000 only: the TBS1000B/EDU and TBS1000C have their own manuals.

Every number below was read from the RENDERED PAGE IMAGES (pdftoppm -r 110), twice, never from extracted text:
  channel counts p. 1-1, DC gain accuracy p. 1-3 (+/-3 % 5 V/div to 10 mV/div, +/-4 % 5 mV/div and 2 mV/div), bandwidth by model p. 1-4,
  long-term sample rate p. 1-7 (+/-50 ppm over any >= 1 ms interval), trigger sensitivity p. 1-9, required equipment p. 4-1, test record p. 4-2,
  self test / self calibration / DC gain p. 4-3 and 4-4, bandwidth p. 4-5, sample rate and delay time p. 4-6 and 4-7, edge trigger p. 4-7 to 4-9,
  external edge trigger p. 4-9 and 4-10.
The DC gain limits are recomputed here in Decimal from the p. 1-3 percentages and the build aborts if the printed table disagrees.

Point fields are those of specs/tektronix_tds2000c_pv.json (the shared Tektronix TDS / TBS engine, tds2000c_verification.py, runs both).
Trigger-stage frequency tags: '10M' = 10 MHz, 'F' = the model's channel trigger frequency (models_info trig_hz), 'BW' = the model's bandwidth
frequency (models_info bw_test_hz), '150M' = 150 MHz, 'LAST' = keep the previous stage's frequency.

Run:  python specs/build_tbs1000_spec.py        (writes next to this script)
"""
import json
from decimal import Decimal as D
from pathlib import Path

OUT = Path(__file__).resolve().parent / 'tektronix_tbs1000_pv.json'

# ---- the eight models (p. 1-1 channel counts, p. 1-4 bandwidths) ---------------------------------------------------------------------------------
# bw_test_hz: bandwidth test frequency (p. 4-5 step 7) and external trigger step 7 (p. 4-10).  trig_hz: channel trigger step 8 (p. 4-8): the
# 150 MHz models run it at 100 MHz and then at 150 MHz (step 12).
MODELS = {
    '1022': dict(channels=2, bw_mhz=25, bw_test_hz=25e6, trig_hz=25e6),
    '1042': dict(channels=2, bw_mhz=40, bw_test_hz=40e6, trig_hz=40e6),
    '1062': dict(channels=2, bw_mhz=60, bw_test_hz=60e6, trig_hz=60e6),
    '1064': dict(channels=4, bw_mhz=60, bw_test_hz=60e6, trig_hz=60e6),
    '1102': dict(channels=2, bw_mhz=100, bw_test_hz=100e6, trig_hz=100e6),
    '1104': dict(channels=4, bw_mhz=100, bw_test_hz=100e6, trig_hz=100e6),
    '1152': dict(channels=2, bw_mhz=150, bw_test_hz=150e6, trig_hz=100e6),
    '1154': dict(channels=4, bw_mhz=150, bw_test_hz=150e6, trig_hz=100e6),
}
FOUR_CH = [m for m, v in MODELS.items() if v['channels'] == 4]
HZ150 = [m for m, v in MODELS.items() if v['bw_mhz'] == 150]

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


def models_for(ch):
    return FOUR_CH if ch > 2 else None


# ---- self test / self calibration (p. 4-3) -------------------------------------------------------------------------------------------------------
add('selftest', 'SELFTEST', 'Self test (power-on diagnostics, no errors)', 1, 1, 1, '', stim='none', passfail=True,
    note='p. 4-3: "Verify that no error messages are displayed". Read back with DIAg:RESUlt:FLAg?. The scope must have run 20 minutes first.')
add('selftest', 'SELFCAL', 'Self calibration (Utility > Do Self Cal passed)', 1, 1, 1, '', stim='none', passfail=True,
    note='p. 4-3: disconnect all probes and cables first; repeat if the ambient temperature changes by 5 degC or more.')

# ---- DC gain accuracy (p. 4-4 table; test record p. 4-2) -------------------------------------------------------------------------------------------
# vscale V/div | +/- source level | printed Vdiff limits | specification % (p. 1-3)
GAIN = [(D('0.005'), D('0.0175'), D('0.0336'), D('0.0364'), D('4')),
        (D('0.2'), D('0.7'), D('1.358'), D('1.442'), D('3')),
        (D('2'), D('7'), D('13.58'), D('14.42'), D('3'))]
for vs, lvl, lo, hi, pct in GAIN:
    nom = 2 * lvl
    half = nom * pct / 100
    if (nom - half, nom + half) != (lo, hi):
        raise SystemExit(f'DC gain {vs} V/div: printed {lo}..{hi} differs from {nom} +/- {pct} % = {nom - half}..{nom + half}')
for ch in (1, 2, 3, 4):
    for vs, lvl, lo, hi, _pct in GAIN:
        txt = f'{float(vs) * 1e3:g} mV/div' if vs < 1 else f'{float(vs):g} V/div'
        add('gain', 'GAIN', f'CH{ch} DC gain, {txt}', float(2 * lvl), float(lo), float(hi), 'V', ch=ch, models=models_for(ch),
            vscale=float(vs), vpos=float(lvl), vneg=float(-lvl), vdiff=float(2 * lvl))

# ---- analog bandwidth (p. 4-5; test record "Channel n Bandwidth": 2.12 V minimum, no maximum) --------------------------------------------------------
for ch in (1, 2, 3, 4):
    add('bw', 'BW', f'CH{ch} bandwidth: 3 V p-p at 50 kHz reference, Vpk-pk at model frequency', 2.12, 2.12, None, 'V', ch=ch, models=models_for(ch),
        vscale=0.5, ref_hz=50e3, ref_target=3.0, ref_low=2.98, ref_high=3.02, hscale_ref=10e-6, hscale=10e-9,
        note='Reference level is set at 10 us/div (5 cycles of 50 kHz on screen) instead of the manual 10 ms/div (p. 4-5 step 4), the deviation the lab '
             'asked for on the TDS2000C (same chapter text); the measured Pk-Pk limits are unchanged. Model frequency 25/40/60/100/150 MHz. 50 ohm feedthrough.')

# ---- sample rate and delay time accuracy (p. 4-6 / 4-7) ---------------------------------------------------------------------------------------------
TB_DIV = D('2')
if TB_DIV * D('250e-9') / D('10e-3') != D('50e-6'):
    raise SystemExit('time base: 2 div x 250 ns / 10 ms is not 50 ppm')
add('timebase', 'TIMEBASE', 'Time base: rising edge of the 10 ms marker at center screen (divisions)', 0.0, -float(TB_DIV), float(TB_DIV), 'div', ch=1,
    period=10e-3, vscale=0.5, hscale_set=1e-3, delay=10e-3, hscale_meas=250e-9,
    note='1 division of displacement = 25 ppm time base error (p. 4-7 note); +/-2 div = the 50 ppm specification (p. 1-7). '
         'Edge position measured from the acquired waveform, not by eye.')

# ---- edge trigger sensitivity (p. 4-7 / 4-8 / 4-9; test record: "Stable trigger") -------------------------------------------------------------------
TRIG_STAGES = [
    dict(step='3-7',   freq='10M',  meas_vpp=0.5,  hscale=25e-9,  slope='RISe', check=True),
    dict(step='8-11',  freq='F',    meas_vpp=0.75, hscale=5e-9,   slope='RISe', check=True),
    dict(step='12',    freq='150M', meas_vpp=1.0,  hscale=5e-9,   slope='RISe', check=True, models=HZ150),
    dict(step='13-15', freq='LAST', meas_vpp='LAST', hscale=2.5e-9, slope='FALL', check=True),
]
for ch in (1, 2, 3, 4):
    add('trig', 'TRIG', f'CH{ch} edge trigger sensitivity (stable trigger)', 1, 1, 1, '', ch=ch, models=models_for(ch), passfail=True,
        vscale=0.5, stages=TRIG_STAGES,
        note='Pass = stable trigger at every stage (engine criteria: trigger state, acquisitions counting, edge position repeatable).')

# ---- external edge trigger sensitivity (p. 4-9 / 4-10) ----------------------------------------------------------------------------------------------
# Step 10 sets 5 ns/div again (the same as step 8); built as printed (the TDS2000C chapter has 2.5 ns/div there; flagged as a possible misprint).
EXT_STAGES = [
    dict(step='3-6',   freq='10M',  src_vpp=0.3, hscale=25e-9,  slope='RISe', check=False, note='about 200 mV p-p on CH1'),
    dict(step='7-9',   freq='BW',   src_vpp='LAST', hscale=5e-9, slope='RISe', check=True),
    dict(step='10-11', freq='LAST', src_vpp='LAST', hscale=5e-9, slope='RISe', check=True),
    dict(step='12-13', freq='LAST', src_vpp='LAST', hscale=5e-9, slope='FALL', check=True),
]
add('exttrig', 'EXTTRIG', 'External edge trigger sensitivity (stable trigger)', 1, 1, 1, '', ch=1, passfail=True,
    vscale=0.1, stages=EXT_STAGES,
    note='CH1 and EXT TRIG both fed from a power splitter, 50 ohm feedthrough terminators on both inputs (figure p. 4-9).')

# Vertical position accuracy (p. 4-10 onwards) is NOT built: left out as on the TDS2000C (lab request); the owner decides.

for i, p in enumerate(points, 1):
    p['id'] = i

spec = dict(schema=2, manufacturer='Tektronix', model='TBS1000', models=list(MODELS), models_info=MODELS,
            title='TBS1000 Series Performance Verification',
            source=dict(document='TBS1000 Series Digital Storage Oscilloscopes Service Manual (077-0772-01 Rev D)',
                        pages='Chapter 4 pp. 4-1 to 4-10 (specifications pp. 1-1 to 1-9)',
                        note='Limits read from rendered page images. Equipment table p. 4-1 (DC source 17.5 mV to 7 V +/-0.5 %, leveled sine 50 kHz and 200 MHz '
                             '+/-3 %, 10 ms time mark +/-10 ppm) is met here by the calibrator scope option. Vertical position accuracy is not built.'),
            not_built=[dict(test='Check Vertical Position Accuracy', pages='4-10 onwards',
                            why='left out like the TDS2000C vertical position test (lab request on the TDS2000C); owner to decide')],
            flags=[dict(point='bw', printed='reference at 10 ms/div (p. 4-5 step 4)', used='10 us/div, as the lab asked for the TDS2000C'),
                   dict(point='exttrig step 10', printed='5 ns/div (same as step 8)', used='as printed (TDS2000C chapter: 2.5 ns/div; possible misprint)'),
                   dict(point='exttrig 1152/1154 at 150 MHz', printed='about 200 mV p-p', spec='350 mV from 100 MHz to 150 MHz (p. 1-9, style B)',
                        used='as printed (stricter than the specification)'),
                   dict(point='model list', printed='TBS1052 appears in the trigger-source table only (p. 1-8)', used='not built (no channel, bandwidth or procedure rows)')],
            sections=[dict(id=s, title=t, page=PAGES[s]) for s, t in TITLES.items()], points=points)
OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
if __name__ == '__main__':
    from collections import Counter
    print(len(points), 'points ->', OUT, dict(Counter(p['section'] for p in points)))
