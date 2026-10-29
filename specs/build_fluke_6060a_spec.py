"""Builds specs/fluke_6060a_pv.json: the Fluke 6060A / 6060A/AF performance tests (Instruction Manual, Section 4A, printed pp. 4A-3 to 4A-17, PDF pages 119 to 133).

Every limit, frequency and level below was read from the RENDERED page images (pdftoppm -r 130, never extracted text) and each number was read twice; the page of every point is in
its 'page' field ('printed / PDF').  Nothing is silently corrected: each printed typo or ambiguity is in the point's 'flags' and in the spec's 'discrepancies'.

Scope agreed with the owner: 6060A on GPIB, two-way automation; 4A-9 and 4A-10 (output leakage) are NOT built.

Run:  python specs/build_fluke_6060a_spec.py        (writes specs/fluke_6060a_pv.json)
All limit arithmetic is Decimal; the JSON holds floats made from the Decimal results.
"""
import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_6060a_pv.json'

# ---- named constants (change here, run the builder again) ------------------------------------------------------------------------------------------------
HIGH_LEVEL_FREQS_MHZ = (0.4, 120, 244, 245, 850, 1050)         # 4A-5 step d and h (printed p. 4A-4 / 4A-6, PDF 121 / 122)
# 4A-6 and 4A-7: the introduction of each test (p. 4A-6 and 4A-7) lists 120, 244, 245, 850 and 1050 MHz; the procedure text programs 30 MHz first (4A-6 step a, 4A-7 step a) and
# then repeats at 244, 245, 850, 1050 MHz.  Owner decision (2026-10-28): use the introduction list.  The manual's 30 MHz procedure text is noted in the report.
MID_LOW_FREQS_MHZ = (120, 244, 245, 850, 1050)
MID_LEVELS_DBM = (-24, -30, -36, -42, -48, -54, -60, -66)       # 4A-6 steps a and f
LOW_LEVEL_DBM = -127                                            # 4A-7
ALT_FREQS_MHZ = (0.4, 120, 244, 245, 850, 1050)                 # 4A-8 step e
ALT_LEVELS_DBM = tuple(11 - 6 * k for k in range(24))           # +11 to -127 dBm in 6 dB steps (step e); 24 levels
HARM_FREQS_MHZ = (0.4, 50, 240, 300, 500, 750)                  # 4A-11 steps c and f
HARM_LEVEL_DBM = 13
HARM_COUNT = 4                                                  # fundamental plus harmonics 2, 3 and 4 ("at least three harmonics wherever possible", step d)
LEVEL_LIMIT_DB = D('1.5')                                       # 4A-5 .. 4A-8
PM_SWITCH_DBM = -20                                             # 4A-8: levels at or above this are read as RF power (M4, 11722A sensor module), lower ones as tuned RF level (S4): UNVERIFIED choice
COUNT_RES_HZ = 10                                               # 'one count' = 10 Hz of the frequency counter of Table 4A-1 (8902A frequency resolution 7.1SP = 10 Hz); owner confirmed 2026-10-28
SECTIONS_4A5 = ((0, 0, 12), (1, 6, 6), (2, 12, 0), (3, 24, -12), (4, 24, -12), (5, 24, -12), (6, 24, -12), (7, 24, -12))   # (section, nominal attenuation dB, programmed dBm): Figure 4A-2
SP_CODE = {4: 'SP83', 5: 'SP84', 6: 'SP85', 7: 'SP86'}
RES_FM_FREQS = {                                                # test 8 (printed p. 4A-16, PDF 132)
    'c': (10, 50, 100, 200, 244),
    'd': (250, 385, 450, 510),
    'e': (512.03999, 750.03999, 850.03999, 900.03999, 950.03999, 1000.03999, 1025.03999, 1049.03999)}
# Table 4A-3 (printed p. 4A-15, PDF 131) and Table 4A-4: programmed depth -> (mean depth min, max, max THD)
TABLE_4A4 = {30: (D('26.8'), D('33.2'), D('1.5')), 70: (D('65.2'), D('74.8'), D('3')), 90: (D('84.4'), D('95.6'), D('5'))}
TABLE_4A3 = ((0.4, (1, 7), (30, 70, 90)), (244.9, (1, 7), (70, 90)), (245, (1, 7), (70, 90)), (512, (1, 7), (70, 90)), (1050, (1, 7), (70, 90)))

PAGES = {'4A-3': '4A-3 / PDF 119', '4A-4': '4A-3, 4A-4 / PDF 119-120', '4A-5': '4A-4 to 4A-6 / PDF 120-122 (Figure 4A-2 p. 4A-5 / PDF 121)', '4A-6': '4A-6 / PDF 122',
         '4A-7': '4A-7, 4A-8 / PDF 123-124', '4A-8': '4A-8, 4A-9 / PDF 124-125', '4A-11': '4A-11, 4A-12 / PDF 127-128',
         'T1': '4A-13 / PDF 129', 'T2': '4A-13 / PDF 129', 'T3': '4A-13, 4A-14, 4A-15 (Tables 4A-3 / 4A-4) / PDF 129-131', 'T4': '4A-14 / PDF 130', 'T5': '4A-14 / PDF 130',
         'T6': '4A-14 to 4A-16 / PDF 130-132', 'T7': '4A-16 / PDF 132', 'T8': '4A-16, 4A-17 / PDF 132-133'}


def f(x):
    return float(x)


def num(x):
    """A float without binary noise (frequencies like 512.03999)."""
    return float(f'{float(x):.9g}')


def mhz_text(mhz):
    return f'{mhz:g} MHz'


# ---- the points -----------------------------------------------------------------------------------------------------------------------------------------
SECTIONS = []
FLAGS_ALL = []


def section(sid, title, page, setup, group):
    s = dict(id=sid, title=title, page=page, setup=setup, group=group, points=[])
    SECTIONS.append(s)
    return s


def add(sec, **kw):
    kw.setdefault('page', PAGES[sec['id']] if sec['id'] in PAGES else sec['page'])
    kw.setdefault('group', sec['group'])
    if kw.get('lf'):                                         # a point with an LF source is its own hook-up group per LF frequency (the generator is set to that frequency)
        kw['group'] = {1000.0: 'EXT1K', 10000.0: 'EXT10K', 400.0: 'EXT400'}[kw['lf']['freq_hz']]
    kw['section'] = sec['id']
    sec['points'].append(kw)
    return kw


def band(nominal, half, unit):
    """low / high = nominal -/+ half (Decimal)."""
    n, h = D(str(nominal)), D(str(half))
    return dict(nominal=f(n), low=f(n - h), high=f(n + h), unit=unit)


def build_spec():
    SECTIONS.clear()
    FLAGS_ALL.clear()
    # ---- 4A-3 power-on -------------------------------------------------------------------------------------------------------------------------------
    s = section('4A-3', '4A-3 Power-on test', PAGES['4A-3'],
                'Switch the 6060A POWER off, then on. The built-in self test runs (every indicator and display segment on for about 5 seconds). If it passes, the generator goes to the Instrument Preset '
                'state; if it fails, the failure codes appear in the four display fields (paragraph 4D-17).', 'POWERON')
    add(s, ref='4A-3 #1', func='SELFTEST', meas='selftest', description='Power-on self test passed', nominal=1.0, low=1.0, high=1.0, unit='',
        flags=['Prompt-based pass / fail: the self test is the generator\'s power-on test and has no remote result the manual confirms (SP02 / IT / SP11 are listed in Section 2 but not verified for this use). '
               'The reading is 1 for passed and 0 for failed.'])
    # ---- 4A-4 synthesis ------------------------------------------------------------------------------------------------------------------------------
    s = section('4A-4', '4A-4 Synthesis test', PAGES['4A-4'],
                'Connect the 6060A rear 10 MHz IN/OUT to the 8902A 10 MHz time base input, REF INT/EXT switch to INT, and the RF OUTPUT to the 8902A RF INPUT (the 8902A replaces the frequency counter). '
                'The program presets the 6060A, programs 111.1111 MHz and a 111.1111 MHz frequency step, and set directly (not by the step keys), up to 999.9999 MHz.', 'RX')
    for n in range(1, 10):
        hz = n * 111111100
        add(s, ref=f'4A-4 #{n}', func='FREQ', meas='freq_count', description=f'Synthesis {n * 111.1111:.4f} MHz', step_index=n,
            gen=dict(freq_mhz=num(n * 111.1111), level_dbm=None), rx=dict(resolution_hz=COUNT_RES_HZ),
            **band(hz, COUNT_RES_HZ, 'Hz'),
            flags=(['One count is the 10 Hz resolution of the Table 4A-1 counter (owner confirmed 2026-10-28); the 8902A reads at 10 Hz resolution (7.1SP).',
                    'The level is not specified in 4A-4: the preset level (-10 dBm) is left unchanged (RF switched on).'] if n == 1 else [])
            + (['Points 2 to 9 are n x 111.1111 MHz: the manual prints only 111.1111, 222.2222 and 999.9999 ("etc.").'] if n == 2 else []))
    # ---- 4A-5 high level -----------------------------------------------------------------------------------------------------------------------------
    s = section('4A-5', '4A-5 High-level accuracy test', PAGES['4A-5'],
                'Power sensor (Fluke 96270A in power-meter mode, R&S NRP40T) on the 6060A RF OUTPUT. The 6060A is preset and each attenuator section is selected with the levels of Figure 4A-2 '
                '(sections 4 to 7: -12 dBm then SP83 to SP86). Level errors, the eight section errors and their sum must not exceed +/-1.5 dB.', 'PM')
    for fi, fmhz in enumerate(HIGH_LEVEL_FREQS_MHZ):
        ids = []
        for sec, nominal_att, level in SECTIONS_4A5:
            p = add(s, ref=f'4A-5 {mhz_text(fmhz)} section {sec}', func='LEVEL', meas='level_pm', description=f'{mhz_text(fmhz)} section {sec}: level {level:+d} dBm',
                    section_no=sec, nominal_att=nominal_att, zero_key=f'4A-5@{fmhz:g}', band_label=mhz_text(fmhz),
                    gen=dict(freq_mhz=fmhz, level_dbm=level, attenuator=SP_CODE.get(sec)), pm=dict(freq_mhz=fmhz),
                    **band(level, LEVEL_LIMIT_DB, 'dBm'),
                    flags=([f'Section {sec} is selected with -12 dBm then {SP_CODE[sec]} ([SPCL][8][{sec - 1}]).'] if sec >= 4 else [])
                    + (['UNVERIFIED: Rohde & Schwarz NRP40T on the 96270A power-meter mode (the 96270A manual never mentions NRP sensors).'] if fi == 0 and sec == 0 else []))
            ids.append(p)
        refs = [q['ref'] for q in ids]
        for n in range(1, 8):
            nominal_att = SECTIONS_4A5[n][1]
            add(s, ref=f'4A-5 {mhz_text(fmhz)} section error {n}', func='SECTION_ERROR', meas='derived', description=f'{mhz_text(fmhz)} section {n} error  (-M0 + M{n} + {nominal_att})',
                derive=dict(kind='section', inputs=[refs[0], refs[n]], constant=nominal_att), zero_key=None, band_label=mhz_text(fmhz),
                **band(0, LEVEL_LIMIT_DB, 'dB'),
                flags=(['Section 1 of the printed example (Figure 4A-3) shows +0.3 but -12.2 + 5.9 + 6 = -0.3: the formula is used, never the example.'] if (n == 1 and fi == 0) else []))
        add(s, ref=f'4A-5 {mhz_text(fmhz)} sum of errors', func='SUM_ERRORS', meas='derived', description=f'{mhz_text(fmhz)} sum of the eight section errors',
            derive=dict(kind='sum', inputs=refs, level0=12, attenuation=[a for _n, a, _l in SECTIONS_4A5]), band_label=mhz_text(fmhz), **band(0, LEVEL_LIMIT_DB, 'dB'),
            flags=(['The sum is (M0 - 12) plus the section errors 1 to 7 (section 0\'s own section error is its level error M0 - 12, so it is not repeated as a separate row).'] if fi == 0 else []))
    # ---- 4A-6 mid level ------------------------------------------------------------------------------------------------------------------------------
    s = section('4A-6', '4A-6 Mid-level accuracy test', PAGES['4A-6'],
                'DEVIATION FROM THE PRINTED METHOD (owner, 2026-10-29): the 8902A tuned RF level measures -24 to -66 dBm instead of a power meter with a low-level sensor; '
                'the R&S NRP40T (a thermal sensor, -35 to +20 dBm) cannot reach -66 dBm. Levels -24 to -66 dBm in 6 dB steps.', 'RX')
    for fmhz in MID_LOW_FREQS_MHZ:
        for lv in MID_LEVELS_DBM:
            add(s, ref=f'4A-6 {mhz_text(fmhz)} {lv} dBm', func='LEVEL', meas='level_rx', description=f'{mhz_text(fmhz)}, {lv} dBm (8902A tuned RF level)',
                gen=dict(freq_mhz=fmhz, level_dbm=lv), rx=dict(freq_mhz=fmhz, mode='tuned'), **band(lv, LEVEL_LIMIT_DB, 'dBm'),
                flags=(['DEVIATION from the printed method (power meter with a low-level sensor, steps b to e): measured with the 8902A tuned RF level, as in 4A-7 and 4A-8 '
                        '(owner, 2026-10-29: the NRP40T thermal sensor stops at -35 dBm).',
                        'The manual\'s procedure (step a) programs 30 MHz first; its introduction lists 120 MHz: the introduction list is used (owner decision).'] if (fmhz == MID_LOW_FREQS_MHZ[0] and lv == -24) else []))
    # ---- 4A-7 low level ------------------------------------------------------------------------------------------------------------------------------
    s = section('4A-7', '4A-7 Low-level accuracy test', PAGES['4A-7'],
                'DEVIATION FROM THE PRINTED METHOD: the 8902A tuned RF level (as in 4A-8) measures -127 dBm instead of the power meter, 60 dB attenuator, wideband amplifier and spectrum analyzer.', 'RX')
    for fmhz in MID_LOW_FREQS_MHZ:
        add(s, ref=f'4A-7 {mhz_text(fmhz)} {LOW_LEVEL_DBM} dBm', func='LEVEL', meas='level_rx', description=f'{mhz_text(fmhz)}, {LOW_LEVEL_DBM} dBm (8902A tuned RF level)',
            gen=dict(freq_mhz=fmhz, level_dbm=LOW_LEVEL_DBM), rx=dict(freq_mhz=fmhz, mode='tuned'), **band(LOW_LEVEL_DBM, LEVEL_LIMIT_DB, 'dBm'),
            flags=(['DEVIATION from the printed method (power meter + 60 dB attenuator + wideband amplifier + spectrum analyzer, steps e to h): measured with the 8902A tuned RF level, as in 4A-8 (owner request).',
                    'The manual\'s procedure (step a) programs 30 MHz first; its introduction lists 120 MHz: the introduction list is used (owner decision).'] if fmhz == MID_LOW_FREQS_MHZ[0] else []))
    # ---- 4A-8 alternate level ------------------------------------------------------------------------------------------------------------------------
    s = section('4A-8', '4A-8 Alternate-level accuracy test', PAGES['4A-8'],
                '8902A with the 11722A sensor module on the RF OUTPUT; 6060A 10 MHz OUT to the 8902A time base input. Levels +11 to -127 dBm in 6 dB steps at six frequencies. '
                'Levels from -20 dBm up are read as RF power (M4); lower levels as tuned RF level (S4).', 'RX')
    # Order: every tuned-level point (all frequencies) first, then every RF-power point, so the 11722A sensor module is moved once (the manual runs level by level at each frequency).
    order = [(fmhz, k, lv) for fmhz in ALT_FREQS_MHZ for k, lv in enumerate(ALT_LEVELS_DBM) if lv < PM_SWITCH_DBM] + \
            [(fmhz, k, lv) for fmhz in ALT_FREQS_MHZ for k, lv in enumerate(ALT_LEVELS_DBM) if lv >= PM_SWITCH_DBM]
    for i, (fmhz, k, lv) in enumerate(order):
        power = lv >= PM_SWITCH_DBM
        add(s, ref=f'4A-8 {mhz_text(fmhz)} {lv:+d} dBm', func='LEVEL', meas='level_rx', description=f'{mhz_text(fmhz)}, {lv:+d} dBm ({"RF power, sensor module" if power else "tuned RF level"})',
            step_index=k + 1, group='RXPWR' if power else 'RX', gen=dict(freq_mhz=fmhz, level_dbm=lv), rx=dict(freq_mhz=fmhz, mode='power' if power else 'tuned'), **band(lv, LEVEL_LIMIT_DB, 'dBm'),
            flags=(['The 24 levels are computed from "+11 dBm to -127 dBm in six dB steps" (the manual does not list them). The points run in an order that moves the sensor module once '
                    '(all tuned-level points, then all RF-power points); the manual runs the levels in turn at each frequency.',
                    'UNVERIFIED: the switch from RF power (sensor module, 11722A) to tuned RF level at -20 dBm is this procedure\'s choice from the 8902A manual, not a 6060A manual statement.',
                    'UNVERIFIED: the sensor module\'s calibration-factor table must already be loaded in the 8902A (this program does not enter it).'] if i == 0 else []))
    # ---- 4A-11 harmonics and spurs -------------------------------------------------------------------------------------------------------------------
    s = section('4A-11', '4A-11 Harmonic and spurious test', PAGES['4A-11'],
                'UUT RF OUTPUT to the HP 8563E input (do not overload the analyzer). Harmonics are measured at +13 dBm; harmonics must be below -30 dBc, spurs below -60 dBc.', 'SA')
    for fmhz in HARM_FREQS_MHZ:
        add(s, ref=f'4A-11 harmonics {mhz_text(fmhz)}', func='HARMONIC', meas='harmonic', description=f'Harmonics 2 to {HARM_COUNT} at {mhz_text(fmhz)}, +{HARM_LEVEL_DBM} dBm (worst, dBc)',
            gen=dict(freq_mhz=fmhz, level_dbm=HARM_LEVEL_DBM), sa=dict(n_max=HARM_COUNT), nominal=-30.0, low=-200.0, high=-30.0, strict_high=True, unit='dBc',
            flags=(['The 8563E has no remote harmonic function: the driver measures the fundamental and then each harmonic by software (CF / TS / MKPK HI). Analyzer settings are this procedure\'s choice (UNVERIFIED).'] if fmhz == 0.4 else []))
    spurs = [  # (ref tag, carrier MHz, level, ext_am, target kind 'abs'|'off', target in Hz, description, page tag)
        ('A', 185, 13, False, 'abs', 245e6, 'step g, h'), ('B', 244, 13, False, 'abs', 312e6, 'step i, j'),
        ('C', 244.99, 0, False, 'off', 20e3, 'step k, l.1'), ('C', 244.99, 0, False, 'off', 30e3, 'step k, l.1'), ('C', 244.99, 0, False, 'off', 35e3, 'step k, l.1'),
        ('C', 244.99, 0, False, 'off', 40e3, 'step k, l.1'), ('C', 244.99, 0, False, 'off', 1e6, 'step l.2'), ('C', 244.99, 0, False, 'off', 10e6, 'step l.2'),
        ('D', 244.99, 1, True, 'abs', 10e6, 'step l.3, l.4'), ('D', 244.99, 1, True, 'abs', 20e6, 'step l.3, l.4'), ('D', 244.99, 1, True, 'abs', 30e6, 'step l.3, l.4'),
        ('D', 244.99, 1, True, 'abs', 800e6, 'step l.5'), ('D', 244.99, 1, True, 'abs', 1044.99e6, 'step l.5'), ('E', 600, 0, False, 'abs', 300e6, 'step l.6, l.7')]
    for i, (tag, carrier, level, ext, kind, target, steps) in enumerate(spurs):
        where = f'offset {target / 1e3:g} kHz' if (kind == 'off' and target < 1e6) else (f'offset {target / 1e6:g} MHz' if kind == 'off' else f'{target / 1e6:g} MHz')
        add(s, ref=f'4A-11 spur {tag} {where}', func='SPUR', meas='spur', description=f'Spur at {where}, carrier {carrier:g} MHz {level:+d} dBm' + (', EXT AM 30 % no input' if ext else ''),
            gen=dict(freq_mhz=carrier, level_dbm=level, am=(dict(pct=30, src='ext', input_applied=False) if ext else None)),
            sa=dict(kind=kind, target_hz=target), nominal=-60.0, low=-200.0, high=-60.0, strict_high=True, unit='dBc', page=f'{PAGES["4A-11"]} ({steps})',
            flags=(['Spur frequencies: "at the offsets of ..." (steps l.1 and l.2) are read as OFFSETS from the carrier (both sides, the worse is taken); every other "spur at ... MHz" '
                    '(steps h, j, l.4, l.5, l.7) is read as an ABSOLUTE frequency. 1044.99 MHz = 244.99 + 800 MHz and 10 / 20 / 30 MHz are multiples of the 10 MHz reference, which is why they are '
                    'not read as offsets. UNVERIFIED reading of the manual.',
                    'The level of spur checks A and B is not restated after step b: +13 dBm (still programmed) is used. The window, RBW and reference level of the analyzer are this procedure\'s choice; the '
                    'reading is the highest peak in that window, so a spur hidden under the noise floor is reported as the floor level.'] if i == 0 else []))
    # ---- 4A-12 modulation ----------------------------------------------------------------------------------------------------------------------------
    s = section('T1', '4A-12 Test 1: Internal modulation oscillator frequency', PAGES['T1'],
                'UUT RF OUTPUT to the 8902A RF INPUT, 10 MHz OUT to its time base. 90 % INT AM, +1 dBm, at the preset 300 MHz; the 8902A audio frequency counter reads the modulation frequency.', 'RX')
    for tag, rate, lo, hi, steps in (('1 kHz', 1000, 970, 1030, 'step d, e'), ('400 Hz', 400, 388, 412, 'step f, g')):
        add(s, ref=f'4A-12 test 1 {tag}', func='MODRATE', meas='mod_rate', description=f'Modulation frequency {tag} (INT AM 90 %, +1 dBm)',
            gen=dict(freq_mhz=300, level_dbm=1, am=dict(pct=90, src='int', rate_hz=rate)), rx=dict(source='am'), nominal=float(rate), low=float(lo), high=float(hi), unit='Hz', page=f'{PAGES["T1"]} ({steps})',
            flags=(['Printed typo, corrected here: step e says the counter reads 970 to 1030 "kHz"; +/-3 % of 1 kHz (Table 4A-2) is 970 to 1030 Hz.'] if rate == 1000 else [])
            + (['UNVERIFIED: the 8902A audio frequency counter (S1) replaces the frequency counter on the demodulated signal.'] if rate == 1000 else []))
    s = section('T2', '4A-12 Test 2: Internal AM accuracy', PAGES['T2'],
                'As test 1: mean AM depth = (+PEAK plus -PEAK)/2 (8902A detector D9, 50 Hz to 15 kHz), 90 % at 400 Hz and 1 kHz rate.', 'RX')
    for tag, rate, steps in (('400 Hz', 400, 'step a, b'), ('1 kHz', 1000, 'step c, d')):
        add(s, ref=f'4A-12 test 2 {tag}', func='AMDEPTH', meas='am_depth', description=f'Mean AM depth, 90 % INT AM at {tag}, +1 dBm',
            gen=dict(freq_mhz=300, level_dbm=1, am=dict(pct=90, src='int', rate_hz=rate)), rx=dict(detector=9, hp=1, lp=2), nominal=90.0, low=84.4, high=95.6, unit='%', page=f'{PAGES["T2"]} ({steps})',
            flags=['The 400 Hz point comes first, as left by test 1 (steps a and b); the frequency is the preset 300 MHz.'] if rate == 400 else [])
    s = section('T3', '4A-12 Test 3: AM accuracy and distortion (external AM)', PAGES['T3'],
                'LF generator (33210A / 33220A / 33250A) to the 6060A MOD INPUT and a DVM (BNC T): 1 kHz at 0.7071 V rms as read by the DVM. 8902A: mean AM depth (D9, 50 Hz to 15 kHz) and audio '
                'distortion at 1 kHz. Table 4A-3 combinations; limits from Table 4A-4.', 'EXT1K')
    first = True
    for fmhz, levels, depths in TABLE_4A3:
        for lv in levels:
            for dep in depths:
                lo, hi, thd = TABLE_4A4[dep]
                base = dict(gen=dict(freq_mhz=fmhz, level_dbm=lv, am=dict(pct=dep, src='ext')), lf=dict(freq_hz=1000.0, vrms=0.7071))
                add(s, ref=f'4A-12 test 3 {mhz_text(fmhz)} {lv} dBm {dep}% depth', func='AMDEPTH', meas='am_depth', description=f'Mean AM depth, {mhz_text(fmhz)}, {lv} dBm, EXT AM {dep} %',
                    rx=dict(detector=9, hp=1, lp=2), nominal=float(dep), low=f(lo), high=f(hi), unit='%', **base,
                    flags=(['The limits are Table 4A-4 (mean depth min / max).'] if first else []))
                add(s, ref=f'4A-12 test 3 {mhz_text(fmhz)} {lv} dBm {dep}% THD', func='THD', meas='thd', description=f'THD, {mhz_text(fmhz)}, {lv} dBm, EXT AM {dep} %',
                    rx=dict(source='am', tone_hz=1000), nominal=0.0, low=0.0, high=f(thd), strict_high=True, unit='%', **base,
                    flags=(['UNVERIFIED: the 8902A audio distortion function (S2, 1 kHz) replaces the distortion analyzer.'] if first else []))
                first = False
    s = section('T4', '4A-12 Test 4: Incidental FM', PAGES['T4'],
                '30 % INT AM at 1 kHz, 1050 MHz, +10 dBm; 8902A peak FM deviation in the 0.3 kHz to 3 kHz bandwidth. Limit < 0.3 x fm = 300 Hz (Table 4A-2).', 'RX')
    add(s, ref='4A-12 test 4', func='INCFM', meas='fm_dev', description='Incidental FM, 30 % INT AM at 1 kHz, 1050 MHz, +10 dBm',
        gen=dict(freq_mhz=1050, level_dbm=10, am=dict(pct=30, src='int', rate_hz=1000)), rx=dict(detector=1, hp=2, lp=1), nominal=0.0, low=0.0, high=300.0, strict_high=True, unit='Hz',
        flags=['Step a prints "10 dBm" (the other modulation tests use 7 dBm or 1 dBm): used as printed.', 'UNVERIFIED: peak detector D1 (positive peak) for "peak FM deviation".'])
    s = section('T5', '4A-12 Test 5: Residual AM', PAGES['T5'], '100 MHz, +7 dBm, no modulation; 8902A rms AM in the 0.05 kHz to 15 kHz bandwidth. Limit < 0.1 % rms.', 'RX')
    add(s, ref='4A-12 test 5', func='RESAM', meas='am_depth', description='Residual AM, 100 MHz, +7 dBm, no modulation',
        gen=dict(freq_mhz=100, level_dbm=7), rx=dict(detector=8, hp=1, lp=2), nominal=0.0, low=0.0, high=0.1, strict_high=True, unit='%',
        flags=['Limit as printed for rms (0.1 %); the manual also prints 0.09 % for an average detector, not used here.'])
    s = section('T6', '4A-12 Test 6: FM accuracy and distortion (external FM)', PAGES['T6'],
                'LF generator to the 6060A MOD INPUT and a DVM: 10 kHz at 707.1 mV rms while stepping the 6060A up from 245 to 1045 MHz in 50 MHz steps (8902A FM in 0.05 to 20 kHz), then 0.4 kHz '
                'while stepping down to 245 MHz (0.05 to 3 kHz). 99.9 kHz deviation, 7 dBm. Limits 93 to 107 kHz and THD < 1 %.', 'EXT10K')
    ups = [245 + 50 * k for k in range(17)]
    downs = list(reversed(ups))
    first = True
    for direction, freqs, rate, lp, lf_hz in (('up', ups, 10000, 3, 10000.0), ('down', downs, 400, 1, 400.0)):
        for fmhz in freqs:
            base = dict(gen=dict(freq_mhz=fmhz, level_dbm=7, fm=dict(khz=99.9, src='ext')), lf=dict(freq_hz=lf_hz, vrms=0.7071))
            add(s, ref=f'4A-12 test 6 {direction} {mhz_text(fmhz)}', func='FMDEV', meas='fm_dev', description=f'FM deviation, {mhz_text(fmhz)}, 99.9 kHz EXT FM at {lf_hz / 1000:g} kHz ({direction})',
                rx=dict(detector=1, hp=1, lp=lp), nominal=99900.0, low=93000.0, high=107000.0, unit='Hz', **base,
                flags=(['UNVERIFIED: peak detector D1 for "peak FM"; 8902A low-pass L3 (> 20 kHz) for the 0.05 to 20 kHz bandwidth.'] if first else []))
            if direction == 'up':
                add(s, ref=f'4A-12 test 6 {direction} {mhz_text(fmhz)} THD', func='THD', meas='thd_typed', description=f'THD, {mhz_text(fmhz)}, EXT FM at 10 kHz (typed from a distortion analyzer)',
                    rx=dict(source='fm', tone_hz=10000), nominal=0.0, low=0.0, high=1.0, strict_high=True, unit='%', typed_only=True, **base,
                    flags=(['The 8902A measures audio distortion only at 1 kHz and 400 Hz (D5 / D6): THD at 10 kHz is typed from the technician\'s own distortion analyzer (HP 339B).'] if first else []))
            else:
                add(s, ref=f'4A-12 test 6 {direction} {mhz_text(fmhz)} THD', func='THD', meas='thd', description=f'THD, {mhz_text(fmhz)}, EXT FM at 0.4 kHz ({direction})',
                    rx=dict(source='fm', tone_hz=400), nominal=0.0, low=0.0, high=1.0, strict_high=True, unit='%', **base)
            first = False
    for tag, khz, lo, hi, steps in (('9.99 kHz', 9.99, 9300.0, 10700.0, 'step k, l'), ('0.999 kHz', 0.999, 930.0, 1070.0, 'step m, n')):
        add(s, ref=f'4A-12 test 6 deviation {tag}', func='FMDEV', meas='fm_dev', description=f'FM deviation {tag} (245 MHz, EXT FM at 0.4 kHz)',
            gen=dict(freq_mhz=245, level_dbm=7, fm=dict(khz=khz, src='ext')), lf=dict(freq_hz=400.0, vrms=0.7071), rx=dict(detector=1, hp=1, lp=1),
            nominal=khz * 1000, low=lo, high=hi, unit='Hz', page=f'{PAGES["T6"]} ({steps})',
            flags=['Frequency (245 MHz) and rate (0.4 kHz) are not restated in steps k to n: the state left by step j is used (inferred).'])
    s = section('T7', '4A-12 Test 7: Incidental AM', PAGES['T7'], '50 kHz deviation, INT FM only at 1 kHz, +7 dBm, 11 MHz; 8902A peak AM in the 0.3 kHz to 3 kHz bandwidth. Limit < 1 %.', 'RX')
    add(s, ref='4A-12 test 7', func='INCAM', meas='am_depth', description='Incidental AM, 50 kHz INT FM at 1 kHz, 11 MHz, +7 dBm',
        gen=dict(freq_mhz=11, level_dbm=7, fm=dict(khz=50.0, src='int', rate_hz=1000)), rx=dict(detector=1, hp=2, lp=1), nominal=0.0, low=0.0, high=1.0, strict_high=True, unit='%')
    s = section('T8', '4A-12 Test 8: Residual FM', PAGES['T8'], 'No modulation; 8902A rms FM, first in the 0.3 kHz to 3 kHz bandwidth, then 0.05 kHz to 15 kHz.', 'RX')
    plan = []
    for bw, h, lp_, groups in (('0.3 kHz to 3 kHz', 2, 1, (('c', 27), ('d', 13), ('e', 27))), ('0.05 kHz to 15 kHz', 1, 2, (('e', 60), ('d', 30), ('c', 60)))):
        for key, limit in groups:
            for fmhz in RES_FM_FREQS[key]:
                plan.append((bw, h, lp_, key, limit, fmhz))
    for i, (bw, h, lp_, key, limit, fmhz) in enumerate(plan):
        add(s, ref=f'4A-12 test 8 {mhz_text(fmhz)} {bw}', func='RESFM', meas='fm_dev', description=f'Residual FM, {mhz_text(fmhz)}, {bw} rms',
            gen=dict(freq_mhz=fmhz, level_dbm=7), rx=dict(detector=8, hp=h, lp=lp_), nominal=0.0, low=0.0, high=float(limit), strict_high=True, unit='Hz', page=f'{PAGES["T8"]} (step {key})',
            flags=(['Printed items: step a programs "4 MHz" (not in any list; it is only the start state, so no point is measured at 4 MHz); Table 4A-2 prints "245 kHz" for the 15 kHz-band '
                    'frequency range, clearly 245 MHz (the 30 Hz limit is used for 250 to 510 MHz as step h says); the level is not specified: +7 dBm is used (the level of tests 5 to 7).',
                    'Limits are the rms values (27 / 13 / 60 / 30 Hz); the average-detector values (24 / 12 / 54 / 27 Hz) are not used.'] if i == 0 else []))
    spec = dict(
        schema=1, kind='rf-generator-pv', model='6060A',
        source=dict(cite='Fluke 6060A / 6060A-AF Synthesized Signal Generator Instruction Manual, Section 4A Performance Tests (printed pp. 4A-3 to 4A-17, PDF pages 119 to 133)',
                    note='Points and limits from the rendered pages; leakage tests 4A-9 and 4A-10 are not built (owner). The 8902A replaces the counter, modulation analyzer, distortion analyzer and (4A-7, 4A-8) '
                         'the power meter chain; 4A-5 uses the 96270A power-meter mode with a Rohde & Schwarz NRP40T; 4A-6 uses the 8902A tuned RF level (owner, 2026-10-29).'),
        options=dict(level_limit_db=f(LEVEL_LIMIT_DB), count_resolution_hz=COUNT_RES_HZ),
        constants=dict(mid_low_freqs_mhz=list(MID_LOW_FREQS_MHZ), high_level_freqs_mhz=list(HIGH_LEVEL_FREQS_MHZ), alt_freqs_mhz=list(ALT_FREQS_MHZ), harm_count=HARM_COUNT),
        discrepancies=[
            '4A-6 / 4A-7: introduction lists 120, 244, 245, 850, 1050 MHz; step a programs 30 MHz first. Introduction list used (owner decision 2026-10-28).',
            'Figure 4A-3 section 1 prints "= +0.3" for -12.2 + 5.9 + 6 (= -0.3); the formulas are used.',
            'Test 1 step e: counter limit "970 and 1030 kHz" is clearly Hz.',
            'Table 4A-2 residual FM: "245 kHz to 512 MHz" for the 15 kHz band is clearly 245 MHz.',
            'Test 8 step a: "4 MHz" is not in any frequency list; the level is not specified (+7 dBm used).',
            'Unspecified levels: 4A-4 (preset -10 dBm), 4A-11 spurs A and B (+13 dBm), test 8 (+7 dBm).',
            '4A-11 steps l.4 and l.5 give no offsets: read as absolute frequencies.',
            '4A-9 / 4A-10 (output leakage) are not built.'],
        sections=[s for s in SECTIONS])
    return spec


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(s['points']) for s in spec['sections'])
    print(f'wrote {OUT.name}: {n} points in {len(spec["sections"])} sections')


if __name__ == '__main__':
    main()
