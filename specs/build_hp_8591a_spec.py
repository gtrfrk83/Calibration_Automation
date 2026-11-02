"""Builds specs/hp_8591a_pv.json: the HP 8591A spectrum analyzer procedure taken from the USAF technical manual T.O. 33K3-4-2864-1, "Calibration Procedure for Spectrum Analyzer 8591A (Hewlett-Packard)",
30 May 2012 (27 PDF pages, printed pages 1 to 25).

Every table value below was read from the RENDERED page images of the PDF (never extracted text) and each number was read twice (Tables 2 to 10 and 12, the limits of 4.1.8, 4.1.13, 4.2, 4.3, 4.11.31 and 4.12);
limits are Decimal arithmetic converted to base units (Hz, s, V, dB, dBm), never recomputed from a formula where the document prints them. SI scaling (kHz, MHz, mV ...) is display only.

The document names its own measuring instruments (Arbiter 1083B, 8340B synthesized sweeper, 436A + 8481A power meter, 8491A attenuator, 5345A counter, 11667A splitter, 8640B signal generator, 3325B function
generator, 3335A frequency synthesizer, 8494B and 8496B step attenuators, 909D termination). The lab's bench has the Fluke 96270A (leveled sine 0.001 Hz to 4.024 GHz, -130 to +24 dBm, internal AM, power-meter
mode with an R&S NRP40T), so every such replacement is this procedure's choice and is flagged UNVERIFIED on the point (owner answers, 2026-11-02: 96270A power-meter mode replaces the 436A / 8481A; Table 12 points below
9 MHz are sourced by the 96270A; the CAL OUT counter reading is typed; the sweep-time modulation is the 96270A's internal AM; the 96270A covers -90 to +10 dBm directly, no step attenuators).
The Calibration Performance Table is "Not Required".

Run:  python specs/build_hp_8591a_spec.py        (writes specs/hp_8591a_pv.json)
"""
import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'hp_8591a_pv.json'
DOC = 'T.O. 33K3-4-2864-1'
MHZ, KHZ = D(10) ** 6, D(10) ** 3

# ---- the document's tables --------------------------------------------------------------------------------------------------------------------------
FREQ_READOUT = ((20, '1499.38', '1500.62'), (10, '1499.68', '1500.32'), (1, '1499.968', '1500.032'))       # 4.2: span MHz, low, high MHz (center 1.5 GHz, sweeper -10 dBm)
NOISE_SB = ((10, -60), (-10, -60), (30, -70), (-30, -70))                                                   # 4.3: marker delta kHz, limit dBc (< )
TABLE2 = ((1800.0, 900, '1386.0', '1494.0', 'MHz'), (1000.0, 900, '770.0', '830.0', 'MHz'), (500.0, 900, '385.0', '415.0', 'MHz'), (100.0, 900, '77.0', '83.0', 'MHz'),
          (50.0, 900, '38.5', '41.5', 'MHz'), (20.0, 900, '15.4', '16.6', 'MHz'), (10.0, 70, '7.8', '8.2', 'MHz'), (5.0, 900, '3.9', '4.1', 'MHz'), (2.0, 900, '1.56', '1.64', 'MHz'),
          (1.0, 900, '780.0', '820.0', 'kHz'), (0.5, 900, '390.0', '410.0', 'kHz'), (0.2, 900, '156.0', '164.0', 'kHz'), (0.1, 900, '78.0', '82.0', 'kHz'))      # span MHz, applied (center) MHz, low, high, unit
TABLE3 = ((0.020, 500.0, '15.4', '16.6', 'ms'), (0.050, 200.0, '38.5', '41.5', 'ms'), (0.100, 100.0, '77.0', '83.0', 'ms'), (0.500, 20.0, '385.0', '415.0', 'ms'), (1.0, 10.0, '770.0', '830.0', 'ms'),
          (10.0, 1.0, '7.7', '8.3', 's'), (50.0, 0.2, '38.5', '41.5', 's'), (100.0, 0.1, '77.0', '83.0', 's'))        # sweep time s, modulation rate Hz, low, high, unit
TABLE4 = ((-2, '-2.2', '-1.8'), (-4, '-4.4', '-3.6'), (-6, '-6.6', '-5.4'), (-8, '-8.75', '-7.25'), (-10, '-10.75', '-9.25'))                     # dB from reference level, low, high (dB)
TABLE5 = ((-10, '-10.75', '-9.25'), (-20, '-20.75', '-19.25'), (-30, '-30.75', '-29.25'), (-40, '-40.75', '-39.25'), (-50, '-50.75', '-49.25'), (-60, '-60.75', '-59.25'), (-70, '-71.00', '-69.00'))
TABLE6 = ((70.7, 3, '150.98', '165.20'), (50.0, 6, '104.69', '118.91'), (35.48, 9, '72.22', '86.44'), (25.0, 12, '48.79', '63.01'))                # % of reference level, dB below, low, high (mV)
TABLE7 = ((-50, -70, 10, None), (-40, -60, 20, '0.5'), (-30, -50, 30, '0.5'), (-20, -40, 40, '0.5'), (-10, -30, 50, '0.5'), (0, -20, 60, '0.75'))     # applied dBm, TI reference level dBm, attenuation dB, limit (+/- dB; None = reference)
TABLE8 = ((-20, -10, None), (-10, 0, '0.5'), (0, 10, '0.5'), (-30, -20, '0.5'), (-40, -30, '0.5'), (-50, -40, '0.5'), (-60, -50, '1.25'), (-70, -60, '1.25'), (-80, -70, '1.25'), (-90, -80, '1.25'))
TABLE9 = ((3e3, 50e3, None), (1e3, 50e3, '0.5'), (10e3, 50e3, '0.4'), (30e3, 500e3, '0.4'), (100e3, 500e3, '0.4'), (300e3, 5e6, '0.4'), (1e6, 10e6, '0.4'), (3e6, 10e6, '0.4'))   # RES BW, span, limit (+/- dB)
TABLE10 = ((3e6, '2.4', '3.6', 'MHz'), (1e6, '0.8', '1.2', 'MHz'), (300e3, '240', '360', 'kHz'), (100e3, '80', '120', 'kHz'), (30e3, '24', '36', 'kHz'), (10e3, '8', '12', 'kHz'),
           (3e3, '2.4', '3.6', 'kHz'), (1e3, '0.8', '1.2', 'kHz'))
TABLE11 = [50 * k for k in range(1, 37)]                                       # MHz: 50 to 1800 in steps of 50 (4.11.6, Table 11)
TABLE12 = (('20 MHz', 20e6), ('10 MHz', 10e6), ('5 MHz', 5e6), ('1 MHz', 1e6), ('200 kHz', 200e3), ('50 kHz', 50e3), ('9 kHz', 9e3))     # (50 MHz is the reference of the column)
FRESP_LIMIT_DB = D('1.5')
FRESP_RANGE_DB = D('2.0')
CAL_OUT_STD = (299999250.0, 300000750.0)           # 4.1.13: 299.99925 to 300.00075 MHz
CAL_OUT_004 = (299999967.0, 300000033.0)           # 4.1.13: 299.999967 to 300.000033 MHz (OPT 004)
CAL_OUT_DBM_LIMITS = (-20.4, -19.6)                # 4.1.8
DANL = (('4.12.13', 'LO region, 1 kHz RBW, 30 Hz VBW (400 kHz and up)', -115.0), ('4.12.20', 'LO region, 3 kHz RBW after MKR -> REF LVL, 30 Hz VBW', -115.0),
        ('4.12.29', '1 MHz to 1.5 GHz at the frequency of the highest response (4.12.25)', -115.0), ('4.12.33', '1.5 GHz to 1.8 GHz at the highest response', -113.0))
SRC_UNV = ('UNVERIFIED: the document names a different instrument for this signal; the Fluke 96270A (leveled sine, no step attenuators) is this procedure\'s choice. The 96270A\'s own amplitude / frequency accuracy '
           'and phase noise are not read here and are assumed good enough for the limit.')
SCALE_ZOOM = ('The document turns SIGNAL TRACK on and waits for AUTO ZOOM; the program centres on the signal itself (CF / SP / MKPK HI / MKF?, each setting read back) because the signal frequency is known and fixed.')
SB = 'HP 8590 series commands read on the rendered Programming Manual pages (PDF p. numbers in the driver); nothing has run on the owner\'s 8591A.'


def num(x):
    return float(f'{float(x):.12g}')


def build_spec():
    sections = []

    def section(sid, title, setup, group):
        s = dict(id=sid, title=title, page=DOC, setup=setup, group=group, points=[])
        sections.append(s)
        return s

    def add(sec, para, **kw):
        kw.setdefault('group', sec['group'])
        kw['page'] = f'{DOC} para {para}'
        kw['section'] = sec['id']
        kw['ref'] = f'{para} ' + kw.pop('tag')
        sec['points'].append(kw)
        return kw

    # 3.3 self-calibration (prompt based; no calibration command is ever sent)
    s = section('H-3', 'Preliminary: analyzer self-calibration', 'Warm up 30 minutes, then run the analyzer\'s own self-calibration from its front panel (User\'s Guide, "Improving Accuracy With Self-Calibration Routines").', 'SELFCAL')
    add(s, '3.3', tag='self-calibration', func='SELFCAL', meas='selfcal', description='Self-calibration routines run after the 30 minute warm-up (1 = done)', nominal=1.0, low=1.0, high=1.0, unit='',
        flags=['Prompt-based pass / fail: "the performance of the TI is only specified after the TI calibration routines have been run". The program never sends a calibration command to the analyzer (bench-first rule); '
               'you run the routines from the front panel and answer yes or no. The reading is 1 for done and 0 for not done.'])

    # 4.1 calibrator output
    s = section('H-4.1', 'Calibrator output (CAL OUT)', '4.1: the analyzer CAL OUT (300 MHz, -20 dBm) is measured with the NRP40T sensor on the 96270A and with a frequency counter.', 'CALPM')
    add(s, '4.1.1 to 4.1.8', tag='CAL OUT level', func='CALOUT', meas='calout_pm', description='CAL OUT amplitude, 300 MHz (-20 dBm)', pm=dict(freq_hz=300e6), zero_key='CALOUT',
        nominal=-20.0, low=CAL_OUT_DBM_LIMITS[0], high=CAL_OUT_DBM_LIMITS[1], unit='dBm',
        flags=['UNVERIFIED substitution: the document compares the CAL OUT peak with a synthesized sweeper through a 3 dB attenuator and then measures the SWEEPER with a 436A power meter + 8481A. Here the NRP40T on the 96270A '
               '(power-meter mode) measures the CAL OUT directly with no attenuator, which needs the CAL OUT level the document calls -20 dBm to be inside the sensor\'s range (the NRP40T thermal sensor stops at -35 dBm).',
               'UNVERIFIED: Rohde & Schwarz NRP40T on the 96270A power-meter mode. The sensor is zeroed with nothing connected to it (a prompt) and then connected to CAL OUT.'])
    s = section('H-4.1b', 'Calibrator output frequency (typed counter reading)', '4.1.10 to 4.1.14: 10 MHz frequency standard to the counter EXT FREQ STD input; counter to CAL OUT (50 ohm).', 'CALCTR')
    for opt, lims, nm in (('std', CAL_OUT_STD, 'standard'), ('004', CAL_OUT_004, 'OPT 004')):
        add(s, '4.1.13', tag=f'CAL OUT frequency ({nm})', func='CALFREQ', meas='calout_ctr', opt=opt, description=f'CAL OUT frequency, 300 MHz ({nm} reference): counter reading',
            nominal=300e6, low=lims[0], high=lims[1], unit='Hz',
            manual_prompt=(f'Read the frequency counter on the analyzer CAL OUT ({nm} frequency reference) and type the frequency in Hz (limits {lims[0]:.0f} to {lims[1]:.0f} Hz).'),
            flags=['Typed reading (owner, 2026-11-02): no counter is driven by this program. The limits are the printed ' + ('299.99925 to 300.00075 MHz.' if opt == 'std' else '299.999967 to 300.000033 MHz (OPT 004).'),
                   'Choose the reference option of the unit under test in the settings; the other point is not run.'])

    # 4.2 frequency readout
    s = section('H-4.2', 'Frequency readout accuracy', '4.2.1: 96270A RF OUTPUT to the analyzer INPUT 50 ohm (the document also ties the 10 MHz references together; the 96270A has no 10 MHz connection used here). '
                '1.5 GHz at -10 dBm, center 1.5 GHz, MKPK HI, marker frequency.', 'SRC')
    for span, lo, hi in FREQ_READOUT:
        add(s, f'4.2.3 to 4.2.11', tag=f'1.5 GHz span {span} MHz', func='FREQRO', meas='freq_marker', description=f'Marker frequency at 1.5 GHz, span {span} MHz (-10 dBm)',
            src=dict(freq_hz=1.5e9, level_dbm=-10.0), ti=dict(cf_hz=1.5e9, span_hz=span * 1e6), nominal=1.5e9, low=num(D(lo) * MHZ), high=num(D(hi) * MHZ), unit='Hz',
            flags=[SRC_UNV + ' (8340B synthesized sweeper -> 96270A).', 'The 96270A is not locked to the analyzer\'s 10 MHz reference here (the document\'s Figure 1 does); its own frequency accuracy is not read from the manual, '
                   'so the reading includes the source error. UNVERIFIED.'])

    # 4.3 noise sidebands
    s = section('H-4.3', 'Noise sidebands', '4.3.1: 96270A RF OUTPUT to the analyzer INPUT, 500 MHz at 0 dBm. Center 500 MHz, span 200 kHz, RBW 1 kHz, VBW 30 Hz; the carrier peak is the reference.', 'SRC')
    for off, lim in NOISE_SB:
        add(s, '4.3.4 to 4.3.12', tag=f'{off:+d} kHz', func='NOISESB', meas='noise_sb', description=f'Noise sideband at {off:+d} kHz from a 500 MHz carrier, below the carrier, limit < {lim} dBc (RBW 1 kHz)',
            src=dict(freq_hz=500e6, level_dbm=0.0), ti=dict(offset_hz=off * 1e3), nominal=float(lim), low=-200.0, high=float(lim), strict_high=True, unit='dBc',
            flags=[SRC_UNV + ' (8640B signal generator, SSB noise < -120 dBc/Hz -> 96270A).', 'UNVERIFIED: the 96270A\'s own phase noise at 10 and 30 kHz offset is not read from the manual; if it is not well below the '
                   'analyzer\'s the reading is the source\'s noise, not the analyzer\'s.', 'The document marks the signal with MKR DELTA at +/- offset; the program uses MKPK HI, MKD, MKN <frequency> and MKA? (the delta amplitude).'])

    # 4.4 frequency span
    s = section('H-4.4', 'Frequency span accuracy (Table 2)', '4.4.1: 96270A RF OUTPUT to the analyzer INPUT. Center and span as Table 2. The document puts the signal on the 9th and the 1st graticule line by '
                'adjusting the sweeper; the program sets the source to the frequencies of those two lines and reads the displayed position of the peak on both.', 'SRC')
    for span, centre, lo, hi, unit in TABLE2:
        sc = MHZ if unit == 'MHz' else KHZ
        add(s, '4.4 Table 2', tag=f'span {span:g} MHz', func='SPAN', meas='span_cal', description=f'Span {span:g} MHz: source frequency difference between graticule lines 9 and 1 (center {centre} MHz)',
            src=dict(level_dbm=-10.0), ti=dict(cf_hz=centre * 1e6, span_hz=span * 1e6), nominal=num(D(str(span)) * MHZ * D('0.8')), low=num(D(lo) * sc), high=num(D(hi) * sc), unit='Hz',
            flags=[SRC_UNV + ' (8340B sweeper -> 96270A).',
                   'UNVERIFIED method: the document tunes the sweeper until the signal sits on graticule line 9, records the frequency, then line 1, and takes the difference. The program sets the source at the nominal '
                   'frequencies of the two lines, reads the displayed position of the signal peak (401-point trace, parabolic interpolation) and reports the frequency difference that would put the peak exactly 320 points apart: '
                   'difference x 320 / measured separation in points. The trace read-out (TDF P, TRA?) is UNVERIFIED on the real analyzer.'])

    # 4.5 sweep time
    s = section('H-4.5', 'Sweep time accuracy (Table 3)', '4.5.1: 96270A RF OUTPUT to the analyzer INPUT, 500 MHz at -10 dBm, 96270A internal AM (triangle, 80 %) at the rate in Table 3. Analyzer: center 500 MHz, zero span, '
                'RBW 3 MHz, linear scale, the sweep time of the row.', 'SRC')
    for st, rate, lo, hi, unit in TABLE3:
        sc = D(1) if unit == 's' else D('0.001')
        add(s, '4.5 Table 3', tag=f'sweep {st:g} s', func='SWEEPTIME', meas='sweep_time', description=f'Sweep time {st:g} s: time of 8 modulation periods at {rate:g} Hz',
            src=dict(freq_hz=500e6, level_dbm=-10.0), am=dict(rate_hz=rate, depth_pct=80.0, shape='TRI'), ti=dict(st_s=st), nominal=num(D(str(st)) * D('0.8')), low=num(D(lo) * sc), high=num(D(hi) * sc), unit='s',
            flags=[SRC_UNV + ' (8640B signal generator + 3325B function generator -> the 96270A internal AM; the 8640B amplitude control for a mid-screen display is not needed).',
                   'The document uses the video trigger and the marker delta on the eighth peak; the program takes one free-run zero-span sweep, finds the rising mid-level crossings of the envelope on the 401-point trace and reports '
                   '8 x the mean crossing spacing x sweep time / 400 (UNVERIFIED method; it needs the modulation period to be known well, 96270A AM rate accuracy is not read here).'] +
                  (['The 96270A internal AM rate has a minimum of 1 Hz (Operator Manual): this row (a rate below 1 Hz) cannot be made and is listed as NOT TESTED.'] if rate < 1.0 else []))

    # 4.6 scale fidelity
    s = section('H-4.6a', 'Scale fidelity, log (Tables 4 and 5)', '4.6.2: 96270A RF OUTPUT to the analyzer INPUT, 50 MHz. The analyzer is at 0 dBm reference level, 10 dB/division. The reference signal (0 dBm at the analyzer input) is measured, then the source is lowered in steps; the marker amplitude change from the reference is read.', 'SRC')
    for tbl, rows in (('Table 4', TABLE4), ('Table 5', TABLE5)):
        for step, lo, hi in rows:
            add(s, f'4.6 {tbl}', tag=f'{step} dB', func='SCALELOG', meas='scale_log', description=f'Log scale fidelity {step:+d} dB from the 0 dBm reference level ({tbl})',
                src=dict(freq_hz=50e6, level_dbm=0.0), scale=dict(step_db=float(step), ref_dbm=0.0), ti=dict(cf_hz=50e6), nominal=float(step), low=num(D(lo)), high=num(D(hi)), unit='dB',
                flags=[SRC_UNV + ' (3335A frequency synthesizer + 8494B / 8496B step attenuators -> 96270A level steps; the "Applied" column is the synthesizer level before a 10 dB attenuator: the analyzer input is the Applied '
                       'level minus 10 dB).', SCALE_ZOOM,
                       'The reading is the marker amplitude at the lowered level minus the marker amplitude at the reference level (the document\'s MKR delta); both are read in the same point, so a point can be re-run alone.'] +
                      (['The document prints the -10 dB row (0 dBm applied) in both Table 4 and Table 5 with the same limits; both are kept.'] if step == -10 else []))
    s = section('H-4.6b', 'Scale fidelity, linear (Table 6)', '4.6.19: linear scale. The reference signal is set to a marker reading of 223.6 mV +/-0.4 mV, then lowered in 3 dB steps; the marker voltage is read (AUNITS V).', 'SRC')
    for pct, db, lo, hi in TABLE6:
        add(s, '4.6 Table 6', tag=f'{pct:g} %', func='SCALELIN', meas='scale_lin', description=f'Linear scale fidelity {pct:g} % of the reference level ({-db} dB below 223.6 mV)',
            src=dict(freq_hz=50e6, level_dbm=0.0), scale=dict(step_db=float(-db), ref_dbm=0.0, ref_v=0.2236), ti=dict(cf_hz=50e6), nominal=num((D(lo) + D(hi)) / 2 / 1000), low=num(D(lo) / 1000), high=num(D(hi) / 1000), unit='V',
            flags=[SRC_UNV + ' (3335A + step attenuators -> 96270A).', SCALE_ZOOM, 'UNVERIFIED: that the marker (MKA?) and the trace answer in volts when AUNITS V is set (the TDF page says so for trace data).'])

    # 4.7 input attenuator
    s = section('H-4.7', 'Input attenuator (Table 7)', '4.7.1: 96270A RF OUTPUT to the analyzer INPUT, 50 MHz. Span 100 kHz, RBW 10 kHz, VBW 100 Hz, log 1 dB/division. Each row raises the source level, the reference level and the '
                'input attenuation by 10 dB together; the displayed level should not change.', 'SRC')
    ref_in = -72.5
    for applied, rl, at, lim in TABLE7[1:]:
        lvl = ref_in + (applied - TABLE7[0][0])
        add(s, '4.7 Table 7', tag=f'{at} dB', func='ATTEN', meas='atten', description=f'Input attenuator {at} dB (reference level {rl} dBm), relative to 10 dB',
            src=dict(freq_hz=50e6, level_dbm=lvl, ref_level_dbm=ref_in), ti=dict(cf_hz=50e6, rl_dbm=float(rl), at_db=at, ref_rl_dbm=float(TABLE7[0][1]), ref_at_db=TABLE7[0][2]),
            nominal=0.0, low=-float(lim), high=float(lim), unit='dB',
            flags=[SRC_UNV + ' (step attenuators 20 dB set for 2 to 3 divisions below the reference level -> the source level that puts the peak 2.5 dB below the first reference level, -72.5 dBm at the analyzer).', SCALE_ZOOM,
                   'The document\'s MKR delta of +/-0.5 dB is the displayed change after the source step of +10 dB is accounted for; the program reports (marker change) minus (source level change), which is 0 for a perfect analyzer (UNVERIFIED reading of the table).'])

    # 4.8 reference level
    s = section('H-4.8', 'Reference level (Table 8)', '4.8.1: 96270A RF OUTPUT to the analyzer INPUT, 50 MHz, span 50 kHz, RBW 3 kHz, VBW 30 Hz, log 1 dB/division. Each row changes the source level and the reference level together; '
                'the displayed level should not change. The reference row is reference level -20 dBm.', 'SRC')
    ref_in8 = -21.5
    for rl, applied, lim in TABLE8[1:]:
        lvl = ref_in8 + (applied - TABLE8[0][1])
        add(s, '4.8 Table 8', tag=f'RL {rl} dBm', func='REFLEVEL', meas='reflevel', description=f'Reference level {rl} dBm, relative to -20 dBm',
            src=dict(freq_hz=50e6, level_dbm=lvl, ref_level_dbm=ref_in8), ti=dict(cf_hz=50e6, rl_dbm=float(rl), ref_rl_dbm=float(TABLE8[0][0])), nominal=0.0, low=-float(lim), high=float(lim), unit='dB',
            flags=[SRC_UNV + ' (step attenuators 10 dB, peak 1 to 2 divisions below the reference level -> the source level that puts the peak 1.5 dB below it, -21.5 dBm at the analyzer for the first row).', SCALE_ZOOM,
                   'As in 4.7 the reading is (marker change) minus (source level change) (UNVERIFIED reading). Rows below about -90 dBm of source level sit close to the analyzer noise floor.'] +
                  (['Table 8 lists -10, 0, +10 dBm applied before the lower values; all rows are measured against the -20 dBm reference row.'] if rl == -10 else []))

    # 4.9 RBW switching
    s = section('H-4.9', 'Resolution bandwidth switching (Table 9)', '4.9.1: analyzer CAL OUT to the analyzer INPUT 50 ohm. Center 300 MHz, log 1 dB/division, VBW 1 kHz. The 3 kHz filter at 50 kHz span is the reference.', 'CALIN')
    for rb, span, lim in TABLE9[1:]:
        add(s, '4.9 Table 9', tag=f'RBW {rb:g} Hz', func='RBWSW', meas='rbw_switch', description=f'Resolution bandwidth switching, {rb / 1e3:g} kHz relative to 3 kHz (span {span / 1e3:g} kHz)',
            ti=dict(cf_hz=300e6, rb_hz=rb, span_hz=span, ref_rb_hz=3e3, ref_span_hz=50e3), nominal=0.0, low=-float(lim), high=float(lim), unit='dB',
            flags=['The 300 MHz CAL OUT signal is the document\'s source here too (no 96270A needed); both bandwidths are measured in the same point.', SCALE_ZOOM])

    # 4.10 RBW accuracy
    s = section('H-4.10', 'Resolution bandwidth accuracy (Table 10)', '4.10.1: 96270A RF OUTPUT to the analyzer INPUT, 50 MHz at 0 dBm, log 1 dB/division. The -3 dB bandwidth of the filter is read.', 'SRC')
    for rb, lo, hi, unit in TABLE10:
        sc = MHZ if unit == 'MHz' else KHZ
        add(s, '4.10 Table 10', tag=f'RBW {rb:g} Hz', func='RBWBW', meas='rbw_bw', description=f'Resolution bandwidth {rb / 1e3:g} kHz: -3 dB width', src=dict(freq_hz=50e6, level_dbm=0.0), ti=dict(cf_hz=50e6, rb_hz=rb),
            nominal=rb, low=num(D(lo) * sc), high=num(D(hi) * sc), unit='Hz',
            flags=[SRC_UNV + ' (3335A -> 96270A).', 'UNVERIFIED method: the document adjusts the knob until the delta marker is at -3 dB on each side of the peak; the program reads the 401-point trace and interpolates the two -3 dB crossings '
                   '(span 6 x RBW, VBW = RBW / 10, at least 30 Hz; shown at 2 dB/division with a +5 dBm reference level so both -3 dB points are on screen, not the document\'s 1 dB/division). The MKBW command (-3 dB width) exists in the language but its read-out is not described, so it is not used.'])

    # 4.11 frequency response
    s = section('H-4.11a', 'Frequency response 50 to 1800 MHz (Table 11)', '4.11.1: 96270A RF OUTPUT to the analyzer INPUT, -20 dBm. Analyzer: span 5 MHz, log 1 dB/division, reference level fixed. Each frequency is compared with 300 MHz at the same level.', 'SRC')
    t11 = []
    for mhz in TABLE11:
        m = add(s, '4.11 Table 11', tag=f'{mhz} MHz', func='FRESP', meas='freq_resp', description=f'Frequency response at {mhz} MHz relative to 300 MHz (Table 11)',
                src=dict(freq_hz=mhz * 1e6, level_dbm=-20.0, ref_freq_hz=300e6), ti=dict(cf_hz=mhz * 1e6, span_hz=5e6, rb_hz=3e3, rl_dbm=-15.0), nominal=0.0, low=-float(FRESP_LIMIT_DB), high=float(FRESP_LIMIT_DB), unit='dB',
                flags=[SRC_UNV + ' (8340B sweeper + 11667A splitter + 436A / 8481A power meter -> 96270A leveled output assumed flat).',
                       'UNVERIFIED: the document measures the source power with a power meter at each frequency; this procedure trusts the 96270A\'s level flatness (not read here), so the result includes the source flatness error. '
                       'The reference is the 96270A at 300 MHz and the same level, not the analyzer CAL OUT.',
                       'The document records the response of each row and judges the most positive and the most negative values (4.11.31); each row is also judged against +/-1.5 dB, which is the same test, and the three derived rows follow.'] +
                      (['300 MHz is the reference frequency: its reading is the repeatability of two measurements (about 0 dB).'] if mhz == 300 else []))
        t11.append(m['ref'])
    s = section('H-4.11b', 'Frequency response below 50 MHz (Table 12)', '4.11.19: 96270A RF OUTPUT to the analyzer INPUT, -20 dBm. The 96270A (not a 3335A) covers 9 kHz to 20 MHz. Each frequency is compared with 300 MHz at the same level; '
                'the table\'s column 4 (relative to 300 MHz) is measured directly.', 'SRC')
    t12 = []
    for name, hz in TABLE12:
        span = {20e6: 1e6, 10e6: 1e6, 5e6: 5e5, 1e6: 1e5, 200e3: 2e4, 50e3: 5e3, 9e3: 2e3}[hz]
        rb = 3e3 if hz >= 1e6 else 1e3
        m = add(s, '4.11 Table 12', tag=name, func='FRESP', meas='freq_resp', description=f'Frequency response at {name} relative to 300 MHz (Table 12)',
                src=dict(freq_hz=hz, level_dbm=-20.0, ref_freq_hz=300e6), ti=dict(cf_hz=hz, span_hz=span, rb_hz=rb, rl_dbm=-15.0), nominal=0.0, low=-float(FRESP_LIMIT_DB), high=float(FRESP_LIMIT_DB), unit='dB',
                flags=[SRC_UNV + ' (3335A frequency synthesizer -> 96270A, which the owner confirmed covers these frequencies).',
                       'The document records column 2 (synthesizer amplitude), column 3 (relative to 50 MHz) and column 4 (relative to 300 MHz by adding the 50 MHz power-meter value); the program measures column 4 directly '
                       '(the analyzer reading at the frequency minus its reading at 300 MHz, both at -20 dBm). The span (and 1 kHz RBW below 1 MHz) is "as required" in the document: this procedure\'s choice.',
                       'UNVERIFIED: the 8591A at 9 kHz sits close to its LO feedthrough at 0 Hz; the reading may be disturbed.'])
        t12.append(m['ref'])
    allrefs = t11 + t12
    s = section('H-4.11c', 'Frequency response: most positive, most negative, total (4.11.31)', 'Computed from the rows of Tables 11 and 12.', 'SRC')
    add(s, '4.11.31.1', tag='most positive', func='FRESPMAX', meas='derived', description='Frequency response: most positive value relative to 300 MHz (limit +1.5 dB)', derive=dict(kind='extreme', op='max', inputs=allrefs),
        nominal=0.0, low=-200.0, high=float(FRESP_LIMIT_DB), unit='dB', flags=['Computed: the most positive reading of Tables 11 and 12.'])
    add(s, '4.11.31.2', tag='most negative', func='FRESPMIN', meas='derived', description='Frequency response: most negative value relative to 300 MHz (limit -1.5 dB)', derive=dict(kind='extreme', op='min', inputs=allrefs),
        nominal=0.0, low=-float(FRESP_LIMIT_DB), high=200.0, unit='dB', flags=['Computed: the most negative reading of Tables 11 and 12.'])
    add(s, '4.11.31.3', tag='total', func='FRESPPP', meas='derived', description='Frequency response: most positive minus most negative (limit 2.0 dB)', derive=dict(kind='extreme', op='range', inputs=allrefs),
        nominal=0.0, low=0.0, high=float(FRESP_RANGE_DB), unit='dB', flags=['Computed: 4.11.31.3, the most positive minus the most negative value. Table 1 also lists a relative flatness of 1.0 dB; the procedure text gives 2.0 dB.'])

    # 4.12 displayed average noise level (typed)
    s = section('H-4.12', 'Displayed average noise level (typed)', '4.12.1: analyzer CAL OUT to the INPUT for the reference-level offset (4.12.2 to 4.12.6), then the 50 ohm termination on the INPUT. The display-line readings are typed.', 'DANL')
    for para, text, lim in DANL:
        add(s, para, tag='noise level', func='DANL', meas='manual', description=f'Displayed average noise level, {text} (limit {lim:g} dBm)', nominal=lim, low=-200.0, high=lim, unit='dBm',
            manual_prompt=(f'Follow the document\'s step {para} on the analyzer: set the display line on the average noise trace, ignoring residual responses, and type the display-line amplitude in dBm (must be {lim:g} dBm or lower). '
                           'The reference-level offset of 4.12.2 to 4.12.6 and the termination on the INPUT come first (see the setup note).'),
            flags=['Typed reading: the document sets a display line by eye on the average noise trace; no automatic average-noise measurement is built (the analyzer\'s LO feedthrough and residual responses need the operator\'s judgement). '
                   'The limit is read as "the display line must be at or below the stated level".',
                   'The reference-level offset the document enters (4.12.6) is an operator step; set it back to 0 dB afterwards.'])

    return dict(
        schema=1, kind='spectrum-analyzer-pv', model='8591A',
        source=dict(cite=f'{DOC}, Calibration Procedure for Spectrum Analyzer 8591A (Hewlett-Packard), 30 May 2012', limits_text='USAF T.O. 33K3-4-2864-1 (HP 8591A)',
                    note='Points and limits are the document\'s own tables. Its measuring instruments (sweeper, power meter, counter, synthesizer, step attenuators, function and signal generators) are replaced by the Fluke 96270A '
                         '(leveled sine, internal AM, NRP40T power-meter mode); each replacement is flagged UNVERIFIED on the point. The Calibration Performance Table is "Not Required". '
                         'The self-calibration (3.3) and the display-line readings of 4.12 are prompts / typed readings.'),
        options=dict(am_rate_min_hz=1.0),
        constants=dict(),
        discrepancies=[
            'Table 3 limits are 0.8 x the sweep time (8 modulation periods), but step 4.5.11 says the marker delta must be "on the eighth signal peak" (7 periods would be 0.7 x). The limits are used as printed; 8 periods are measured.',
            'The -10 dB row (0 dBm applied) is printed in both Table 4 and Table 5 with the same limits; both are kept.',
            'Table 1 lists a relative flatness of 1.0 dB; paragraph 4.11.31.4 gives 2.0 dB for the most positive minus the most negative value. 2.0 dB is used.',
            'Table 1 gives the frequency reference aging for the standard unit as < 2 x 10^-6 per year; the paragraph limits 299.99925 to 300.00075 MHz are +/-2.5 ppm and are used as printed.',
            'The document\'s measuring instruments are replaced by the 96270A (sweeper, power meter, counter, synthesizer, step attenuators, signal and function generators); see the flags. The 436A / 8481A power-meter step of 4.1 and 4.11 and the '
            '3 dB attenuator of 4.1.2 have no equivalent here.',
            'The 50 s and 100 s sweep-time rows need a 0.2 Hz and a 0.1 Hz modulation; the 96270A internal AM goes down to 1 Hz only (Operator Manual), so those two rows are listed as NOT TESTED.',
            'Figures 1 to 4 are not reproduced; hook-up diagrams are supplied by the owner as PNG files in diagrams/ (hook_8591A_<GROUP>.png).'],
        sections=sections)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(s['points']) for s in spec['sections'])
    print(f'wrote {OUT.name}: {n} points in {len(spec["sections"])} sections')


if __name__ == '__main__':
    main()
