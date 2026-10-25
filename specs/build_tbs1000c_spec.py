"""Builds specs/tektronix_tbs1000c_pv.json from the TBS1000C Series Oscilloscope Specification and Performance Verification manual
(077-1583-03 Rev A, September 2024), "Performance verification" pp. 23 to 31 (the printed page numbers equal the PDF page numbers).

Every number below was read from the RENDERED PAGE IMAGES (pdftoppm -r 110), twice, never from extracted text:
  model overview p. 9 (TBS1052C / TBS1072C / TBS1102C / TBS1202C: 50 / 70 / 100 / 200 MHz, two channels each),
  DC gain accuracy p. 12 (+/-3.0 %), long-term sample rate p. 15 (+/-25 x 10^-6 over any >= 1 ms interval), trigger sensitivity p. 17,
  required equipment p. 23, test record p. 24, self test p. 24, signal calibration p. 25, DC gain p. 25-26, bandwidth p. 26-27,
  sample rate / delay time p. 27, edge trigger p. 27-29, Aux In edge trigger p. 29-30.
The DC gain limits are recomputed here in Decimal from the +/-3.0 % specification (p. 12) and the build aborts if the printed table disagrees.

Point fields are those of specs/tektronix_tds2000c_pv.json (the shared Tektronix TDS / TBS engine, tds2000c_verification.py, runs both):
section, kind, desc, ch, nominal, low, high (None = one-sided), unit, stim ('cal' | 'none'), models (omitted = all), plus per-kind parameters.
Trigger-stage frequency tags: '10M' = 10 MHz, 'F' = the model's trigger-test frequency (models_info trig_hz), 'BW' = the model's bandwidth-test
frequency (models_info bw_test_hz), '150M' = 150 MHz, 'LAST' = keep the previous stage's frequency.

Run:  python specs/build_tbs1000c_spec.py        (writes next to this script)
"""
import json
from decimal import Decimal as D
from pathlib import Path

OUT = Path(__file__).resolve().parent / 'tektronix_tbs1000c_pv.json'

# ---- the four models (p. 9 model overview; all two-channel, 1 GS/s, 20k points) --------------------------------------------------------
# bw_test_hz: frequency of the bandwidth test (p. 26 step 7). trig_hz: frequency of the edge-trigger step 8 (p. 28) and of the Aux In step 7 (p. 30).
MODELS = {
    '1052C': dict(channels=2, bw_mhz=50, bw_test_hz=50e6, trig_hz=50e6),
    '1072C': dict(channels=2, bw_mhz=70, bw_test_hz=70e6, trig_hz=70e6),
    '1102C': dict(channels=2, bw_mhz=100, bw_test_hz=100e6, trig_hz=100e6),
    '1202C': dict(channels=2, bw_mhz=200, bw_test_hz=200e6, trig_hz=200e6),
}
HZ200 = ['1202C']            # p. 28 step 12: "For the TBS1202C model, set the frequency to 150 MHz, and increase the amplitude to 1 Vp-p"

TITLES = {'selftest': 'Self test and signal calibration', 'gain': 'DC gain accuracy', 'bw': 'Analog bandwidth',
          'timebase': 'Sample rate and delay time accuracy', 'trig': 'Edge trigger sensitivity',
          'exttrig': 'Aux In edge trigger sensitivity'}
PAGES = {'selftest': '24', 'gain': '25', 'bw': '26', 'timebase': '27', 'trig': '27', 'exttrig': '29'}
points = []


def add(sec, kind, desc, nominal, low, high, unit, ch=None, models=None, stim='cal', **kw):
    p = dict(section=sec, kind=kind, desc=desc, ch=ch, nominal=nominal, low=low, high=high, unit=unit, stim=stim)
    if models:
        p['models'] = models
    p.update(kw)
    points.append(p)


# ---- self test (p. 24) and signal calibration (p. 25). Not test-record rows, but the chapter requires both before it ------------------------
add('selftest', 'SELFTEST', 'Self test (power-on diagnostics, no errors)', 1, 1, 1, '', stim='none', passfail=True,
    note='p. 24: "Verify that no error messages are displayed". Read back with DIAg:RESUlt:FLAg?. The scope must have run 20 minutes first.')
add('selftest', 'SELFCAL', 'Signal calibration (Utility > Do Self Cal passed)', 1, 1, 1, '', stim='none', passfail=True,
    note='p. 25: disconnect all probes and cables from channels 1 and 2 first; repeat if the ambient temperature changes by 5 degC or more.')

# ---- DC gain accuracy (p. 25 step 4 table; test record p. 24) --------------------------------------------------------------------------------
# vscale V/div | +/- source level | printed Vdiff limits.  Vdiff = Vpos - Vneg.  Specification p. 12: +/-3.0 % (derated 0.1 %/degC above 30 degC).
GAIN = [(D('0.005'), D('0.0175'), D('0.03395'), D('0.03605')),
        (D('0.2'), D('0.7'), D('1.358'), D('1.442')),
        (D('2'), D('7'), D('13.58'), D('14.42'))]
SPEC_PCT = D('3.0')
for vs, lvl, lo, hi in GAIN:
    nom = 2 * lvl
    half = nom * SPEC_PCT / 100
    if (nom - half, nom + half) != (lo, hi):
        raise SystemExit(f'DC gain {vs} V/div: printed {lo}..{hi} differs from {nom} +/- {SPEC_PCT} % = {nom - half}..{nom + half}')
for ch in (1, 2):
    for vs, lvl, lo, hi in GAIN:
        txt = f'{float(vs) * 1e3:g} mV/div' if vs < 1 else f'{float(vs):g} V/div'
        add('gain', 'GAIN', f'CH{ch} DC gain, {txt}', float(2 * lvl), float(lo), float(hi), 'V', ch=ch,
            vscale=float(vs), vpos=float(lvl), vneg=float(-lvl), vdiff=float(2 * lvl))

# ---- analog bandwidth (p. 26-27; test record "Channel n Bandwidth": 2.12 V, no high limit) ------------------------------------------------------
# The manual itself sets the 50 kHz reference at 10 us/div (p. 26 step 4), so the TDS2000C deviation (10 us/div instead of 10 ms/div) is not needed.
for ch in (1, 2):
    add('bw', 'BW', f'CH{ch} bandwidth: 3 V p-p at 50 kHz reference, Vpk-pk at model frequency', 2.12, 2.12, None, 'V', ch=ch,
        vscale=0.5, ref_hz=50e3, ref_target=3.0, ref_low=2.98, ref_high=3.02, hscale_ref=10e-6, hscale=10e-9,
        note='p. 26: reference 2.98 to 3.02 V p-p at 50 kHz (10 us/div), then the model frequency (50/70/100/200 MHz) at 10 ns/div; '
             'Pk-Pk must be >= 2.12 V. 50 ohm feedthrough termination at the scope input.')

# ---- sample rate and delay time accuracy (p. 27) ----------------------------------------------------------------------------------------------------
# 1 ms time mark, 500 mV/div, 1 ms/div, trigger 50 %, delay 1.0000 ms, then 10 ns/div. Step 13 limit: +/-2.5 divisions (+/-25 ns); the note: one
# division = 10 ppm.  The test record (p. 24) prints -2 / +2 divs; the procedure step and the +/-25 x 10^-6 specification (p. 15) give 2.5 div.
TB_DIV = D('2.5')
if TB_DIV * D('10e-9') / D('1e-3') != D('25e-6'):
    raise SystemExit('time base: 2.5 div x 10 ns / 1 ms is not 25 ppm')
add('timebase', 'TIMEBASE', 'Time base: rising edge of the 1 ms marker at center screen (divisions)', 0.0, -float(TB_DIV), float(TB_DIV), 'div', ch=1,
    period=1e-3, vscale=0.5, hscale_set=1e-3, delay=1e-3, hscale_meas=10e-9, printed_record_limits=[-2.0, 2.0],
    note='p. 27 step 13: within +/-2.5 divisions (+/-25 ns); 1 division = 10 ppm. The test record (p. 24) prints -2 / +2 divs: '
         'the procedure step and the 25 ppm specification (p. 15) are used (flagged for the owner). Edge position measured from the acquired waveform.')

# ---- edge trigger sensitivity (p. 27-29; test record: "Stable trigger") ------------------------------------------------------------------------------
TRIG_STAGES = [
    dict(step='3-7',   freq='10M',  meas_vpp=0.5,  hscale=20e-9, slope='RISe', check=True),
    dict(step='8-11',  freq='F',    meas_vpp=0.75, hscale=4e-9,  slope='RISe', check=True),
    dict(step='12',    freq='150M', meas_vpp=1.0,  hscale=4e-9,  slope='RISe', check=True, models=HZ200),
    dict(step='13-15', freq='LAST', meas_vpp='LAST', hscale=2e-9, slope='FALL', check=True),
]
for ch in (1, 2):
    add('trig', 'TRIG', f'CH{ch} edge trigger sensitivity (stable trigger)', 1, 1, 1, '', ch=ch, passfail=True,
        vscale=0.5, stages=TRIG_STAGES,
        note='Pass = stable trigger at every stage (engine criteria: trigger state, acquisitions counting, edge position repeatable).')

# ---- Aux In edge trigger sensitivity (p. 29-30) ---------------------------------------------------------------------------------------------------------
# src_vpp = the level set on the calibrator (into the power splitter, about 300 mV p-p -> about 200 mV p-p on CH1 and on AUX IN).
EXT_STAGES = [
    dict(step='3-6',   freq='10M',  src_vpp=0.3, hscale=20e-9, slope='RISe', check=False, note='about 200 mV p-p on CH1'),
    dict(step='7-9',   freq='BW',   src_vpp='LAST', hscale=4e-9, slope='RISe', check=True),
    dict(step='10-11', freq='LAST', src_vpp='LAST', hscale=2e-9, slope='RISe', check=True),
    dict(step='12-13', freq='LAST', src_vpp='LAST', hscale=2e-9, slope='FALL', check=True),
]
add('exttrig', 'EXTTRIG', 'Aux In edge trigger sensitivity (stable trigger)', 1, 1, 1, '', ch=1, passfail=True,
    vscale=0.1, stages=EXT_STAGES,
    note='CH1 and AUX IN both fed from a power splitter, 50 ohm feedthrough terminators on both inputs (figure p. 29).')

# Check Vertical Offset Accuracy (pp. 30-31, Table 3) is NOT built: the TDS2000C procedure this one follows leaves its vertical position test out at the
# lab's request; the owner decides whether to add it (question in the report).

for i, p in enumerate(points, 1):
    p['id'] = i

spec = dict(schema=2, manufacturer='Tektronix', model='TBS1000C', models=list(MODELS), models_info=MODELS,
            title='TBS1000C Series Performance Verification',
            source=dict(document='TBS1000C Series Oscilloscope Specification and Performance Verification (077-1583-03 Rev A)',
                        pages='Performance verification pp. 23 to 30 (specifications pp. 9 to 17)',
                        note='Limits read from rendered page images. Equipment table p. 23 (DC source 17.5 mV to 7 V +/-0.5 %, leveled sine 50 kHz and 200 MHz '
                             '+/-3 %, time mark 10 ms period +/-10 ppm; the procedure uses a 1 ms mark) is met here by the calibrator scope option. '
                             'Vertical offset accuracy (pp. 30-31) is not built.'),
            not_built=[dict(test='Check Vertical Offset Accuracy', pages='30-31',
                            why='left out like the TDS2000C vertical position test (lab request on the TDS2000C); owner to decide')],
            flags=[dict(point='timebase', printed='test record p. 24: -2 / +2 divs', used='+/-2.5 div (p. 27 step 13, 25 ppm spec p. 15)'),
                   dict(point='trig 1202C step 8-11', printed='0.75 V p-p (1.5 div) at 200 MHz', spec='2.0 div above 100 MHz to 200 MHz (p. 17, style B)',
                        used='as printed (stricter than the specification)'),
                   dict(point='exttrig 1202C step 7-13', printed='about 200 mV p-p at 200 MHz', spec='350 mV from 100 MHz to 200 MHz (p. 17, style B)',
                        used='as printed (stricter than the specification)')],
            sections=[dict(id=s, title=t, page=PAGES[s]) for s, t in TITLES.items()], points=points)
OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding='utf-8')
if __name__ == '__main__':
    from collections import Counter
    print(len(points), 'points ->', OUT, dict(Counter(p['section'] for p in points)))
