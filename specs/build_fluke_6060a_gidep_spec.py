"""Builds specs/fluke_6060a_gidep_pv.json: the Fluke 6060A / 6060A-AN procedure taken from the GIDEP document T.O. 33K3-4-911-1, "Calibration Procedure for Synthesized Signal Generator
6060 A/AN (Fluke)", 30 April 2017 (25 numbered pages and Appendix A). The Instruction Manual procedure (specs/fluke_6060a_pv.json) is a separate procedure and is not touched.

Every table value below was read from the RENDERED page images of the GIDEP PDF (never extracted text) and each number was read twice; limits are Decimal arithmetic, never recomputed
from a formula where the document prints them. The document names its own measuring instruments (Arbiter 1083A, Agilent 53132A, E4418B + 8482A, N5530SE26 microwave measurement receiver,
E4440A, E8257D, R&S FMAV, Tracor 527E); the lab's bench is the HP 8902A, Fluke 96270A + NRP40T and HP 8563E, so every such mapping is this procedure's choice and is flagged UNVERIFIED on the point.
Calibration Performance Table: "Not Required". Appendix A (reference oscillator adjustment, C153) is an adjustment and is not built.

Run:  python specs/build_fluke_6060a_gidep_spec.py        (writes specs/fluke_6060a_gidep_pv.json)
"""
import json
from decimal import Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'fluke_6060a_gidep_pv.json'
DOC = 'T.O. 33K3-4-911-1'

# ---- the document's tables --------------------------------------------------------------------------------------------------------------------------
TABLE2_MHZ = [D('100.00000') + D('11.11111') * k for k in range(10)]          # 100, 111.11111 ... 199.99999 (Table 2: the last value is printed 199.99999)
TABLE2_MHZ[-1] = D('199.99999')
TABLE2_MHZ[0] = D('100.00000')
TABLE3_MHZ = [D('299.99999'), D('399.99999'), D('499.99999')]
def hz_text(hz):
    """399999980 -> '399 999 980' (the grouping the 10 MHz reference prompt uses)."""
    return f'{int(hz):,}'.replace(',', ' ')


FCO = 'the Fluke 96270A frequency counter (rear 300 MHz Counter BNC) on the lab GPS 10 MHz (owner, 2026-11-04: "use the frequency counter built into the 96270")'
FCO_RANGE_LOW, FCO_RANGE_HIGH = 2, 3        # :FCOunter:RANGe 2 = 50 MHz @ 50 ohm, 3 = 300 MHz @ 50 ohm (Remote Programmers Manual p. 41)
FCO_GATE_S = 2.0                            # :TRIG:GATE 2 (p. 42): 8 / 9 digits (Product Specifications): 1 Hz at 10 MHz (the reference output)
FCO_GATE_RF_S = 20.0                        # owner bench 2026-11-04: at 2 s the 100 to 300 MHz readings came in 10 Hz steps (8 digits) against +/-10 Hz limits; 20 s gives 9 / 10 digits, 1 Hz
FCO_LEVEL_DBM = 7.0                         # the counter needs 0.5 V pk-pk minimum (about -2 dBm into 50 ohm); +7 dBm is 1.4 V pk-pk, under its +/-5 V pk maximum
COUNTER_MAX_MHZ = D('310')


def rx_fm_max_dev_hz(carrier_mhz):
    """The largest peak deviation the 8902A specifies FM accuracy for (p. 1-20, specs/standards/hp_8902a_standard.json): 40 kHz for 250 kHz to 10 MHz carriers, 400 kHz from 10 MHz
    to 1300 MHz. Table 8's 50 kHz on the 250 kHz carrier is above it and is left out (owner, 2026-11-04)."""
    return 40e3 if float(carrier_mhz) < 10 else 400e3                 # 96270A frequency counter, specified 0.9 to 310 MHz (96000 Series Product Specifications, Frequency Counter)
COUNT_STEP_MHZ = D('0.00001')                                                 # the printed limits are the applied value +/-0.00001 MHz (10 Hz), 1 count of the counter's LSD
REF_LOW_HZ, REF_HIGH_HZ = 9999940, 10000060                                   # 4.1.5
DOC_LOW_MHZ = 0.1                                                              # the document's low carrier for Tables 4 to 7: 100 kHz
LOW_MHZ = 0.15                                                                 # used instead (owner, 2026-11-03): the 8902A RF input starts at 150 kHz
TABLE4_FREQS = (LOW_MHZ, 250, 520)                                             # 150 kHz (document: 100 kHz), 250 MHz, 520 MHz (Tables 4, 6, 7)
TUNED_LOW_MHZ = 2.5                                                            # Table 5 low carrier (owner, 2026-11-03): the 8902A tuned RF level is specified from 2.5 MHz (p. 1-22);
TABLE5_FREQS = (TUNED_LOW_MHZ, 250, 520)                                       # 0.15MZ with S4 gave error 20 on the bench (2026-11-03)
MOVED_TUNED = ('Carrier changed from the document\'s 100 kHz to 2.5 MHz (owner, 2026-11-03): the 8902A tuned RF level is specified from 2.5 MHz to 1300 MHz (manual p. 1-22); '
               'at 150 kHz it showed error 20 (value out of range) on the bench. The 6060A level below 2.5 MHz is not verified by Table 5; the limits are the document\'s.')
MOVED = (f'Carrier changed from the document\'s 100 kHz to 150 kHz (owner, 2026-11-03): the 8902A RF input range starts at 150 kHz. '
         'The 6060A between 100 kHz and 150 kHz is not verified by this procedure; the limits are the document\'s (they do not depend on the carrier).')
TABLE4_LEVELS = ((13, '10.5', '15.5'), (10, '7.5', '12.5'), (0, '-2.5', '2.5'))
TABLE5_LEVELS = (0, -10, -20, -30, -40, -50, -60, -70, -80, -90, -100, -110, -120)   # 0 dBm is the reference; the document's -127 dBm row is left out (owner, 2026-11-03: 'stop at -120dB')
TABLE5_TOL = D('2.5')
MOD_LEVEL_DBM, MOD_CARRIER_MHZ = 1, 300           # 4.3: AMPL 1 dBm (printed); the carrier is not printed (RCL 9,8 is a stored state): 300 MHz is this procedure's choice
AM_LEVEL_DBM = 7                                   # 4.4
TABLE6 = ((30, '28.2', '31.8'), (50, '47.0', '53.0'), (70, '65.8', '74.2'), (90, '84.6', '95.4'))     # 1 kHz rate; the 50 % row also carries the < 5 % THD limit
TABLE7 = ((30, '28.2', '31.8'), (70, '65.8', '74.2'), (90, '84.6', '95.4'))                           # 400 Hz rate
AM_THD_MAX = 5.0
TABLE8 = ((0.25, ((10, '9.50', '10.50'), (25, '23.75', '26.25'), (50, '47.50', '52.50'))),
          (250, ((100, '95.00', '105.00'), (250, '237.50', '262.50'), (380, '361.00', '399.00'))),
          (520, ((100, '95.00', '105.00'), (250, '237.50', '262.50'), (380, '361.00', '399.00'))))   # carrier MHz -> (deviation kHz, low, high)
FM_LEVEL_DBM = 7
TABLE9 = dict(freqs=(30, 250, 500), rates=(100, 4000, 8000), devs=(10, 30, 47), limit=3, range_khz=50)
TABLE10 = dict(freqs=(30, 250, 500), rates=(100, 4000, 8000), devs=(100, 300, 370), limit=30, range_khz=500)
TABLE11 = ((0.01, -26), (5, -26), (9.9, -26), (10.1, -30), (250, -30), (520, -30))                    # MHz, limit dBc
HARM_LEVEL_DBM, HARM_COUNT = 13, 4
# Table 12: (spur MHz as printed, carrier MHz, carrier dBm); '*' sets 0 dBm and '**' 1 dBm for the rows from there on
TABLE12 = [('245.00000', 185, 13), ('312.00000', 244, 13),
           ('244.99006', 244.99, 0), ('244.99012', 244.99, 0), ('244.99018', 244.99, 0), ('245.00000', 244.99, 0), ('245.00500', 244.99, 0), ('245.01000', 244.99, 0), ('245.19000', 244.99, 0),
           ('254.99000', 244.99, 0), ('254.99000', 244.99, 1), ('264.99000', 244.99, 1), ('274.99000', 244.99, 1), ('284.99000', 244.99, 1), ('364.99000', 244.99, 1),
           ('444.99000', 244.99, 1), ('1244.99000', 244.99, 1), ('1289.98000', 244.99, 1)]
SPUR_LIMIT_DBC = -35
APPROACH_FROM_MHZ, APPROACH_BAND = 242.0, (242.0, 245.0)     # owner bench 2026-11-03: a carrier of 244 / 244.99 MHz set directly gave UNCAL; from 242 MHz upward in 1 MHz steps it did not
APPROACH_NOTE = ('The 6060A is taken to this carrier from 242 MHz upward in 1 MHz steps (each read back): set directly, 244 MHz gave UNCAL on the bench (owner, 2026-11-03). '
                 'UNVERIFIED which carriers need it; only those from 242 to 245 MHz get the approach.')


def approach(carrier_mhz):
    """The intermediate frequencies (MHz) before the carrier, or [] when the carrier is outside APPROACH_BAND."""
    if not APPROACH_BAND[0] < carrier_mhz < APPROACH_BAND[1]:
        return []
    out, f = [], APPROACH_FROM_MHZ
    while f < carrier_mhz - 1e-9:
        out.append(f)
        f += 1.0
    return out
RESFM_MHZ, RESFM_DBM, RESFM_MAX_HZ = 520, 13, 200                                                     # 4.8
RESAM_DBM, RESAM_MAX_PCT = 9, 0.1                                                                     # 4.9 (the frequency stays at 520 MHz)
COUNT_RES_HZ = 10
DEVM_LEVEL_DBM = 7          # 4.6.3: the signal is set to 7 dBm


def fm_limit_hz(carrier_mhz):
    """The largest FM deviation the 96270A allows (Operator Manual Table 3-26)."""
    return 300e3 if carrier_mhz <= 31.4375 else 750e3 if carrier_mhz <= 125.75 else 0.0012 * carrier_mhz * 1e6
FM_MAX_KHZ = 500.0          # Table 1: FM 1 to 500 kHz deviation (owner, 2026-11-02: allow deviations above the manual's 99.9 kHz on this procedure)

UNV = 'UNVERIFIED: the document names a different instrument; the choice of the lab\'s bench instrument for this step is this procedure\'s.'


def f(x):
    return float(x)


def num(x):
    return float(f'{float(x):.9g}')


def lvl(v):
    return '0' if v == 0 else f'{v:+g}'


def fname(mhz):
    return f'{mhz * 1000:g} kHz' if mhz < 1 else f'{mhz:g} MHz'


def build_spec():
    sections = []

    def section(sid, title, setup, group):
        s = dict(id=sid, title=title, page=f'{DOC}', setup=setup, group=group, points=[])
        sections.append(s)
        return s

    def add(sec, para, **kw):
        kw.setdefault('group', sec['group'])
        kw['page'] = f'{DOC} para {para}'
        kw['section'] = sec['id']
        kw['ref'] = f'{para} ' + kw.pop('tag')
        sec['points'].append(kw)
        return kw

    # 3 preliminary: the self test
    s = section('G-3', 'Preliminary: power-on self test', 'Switch the 6060A POWER on with the RF output OFF. The built-in self test runs (about 5 seconds); if it passes the generator goes to the Instrument Preset state. '
                'Warm up one hour with RF OFF (the reference oscillator needs 24 hours powered).', 'POWERON')
    add(s, '3', tag='self test', func='SELFTEST', meas='selftest', description='Power-on self test passed', nominal=1.0, low=1.0, high=1.0, unit='',
        flags=['Prompt-based pass / fail: the document says only that the self test takes about 5 s. The reading is 1 for passed and 0 for failed. UNVERIFIED: no remote self-test result is confirmed.'])

    # 4.1 frequency accuracy
    s = section('G-4.1', 'Frequency accuracy', '4.1.5: 6060A rear 10 MHz IN/OUT (REF INT) to the 96270A rear 300 MHz Counter BNC; the 96270A is on the lab GPS 10 MHz (external reference).', 'FCOREF')
    add(s, '4.1.5', tag='10 MHz reference output', func='REFFREQ', meas='fco_freq', fco=dict(range=FCO_RANGE_LOW, gate_s=FCO_GATE_S),
        description='Reference oscillator 10 MHz IN/OUT frequency (counter), 9 999 940 to 10 000 060 Hz', nominal=10000000.0, low=float(REF_LOW_HZ), high=float(REF_HIGH_HZ), unit='Hz',
        flags=[UNV + ' (53132A counter -> ' + FCO + ', range 50 MHz @ 50 ohm, 2 s gate).', 'The limits are the printed 9,999,940 Hz to 10.000 060 MHz (+/-6 ppm, Table 1). UNVERIFIED that '
               'the 6060A rear 10 MHz output reaches the counter\'s 0.5 V pk-pk minimum.'])
    s = section('G-4.1b', 'Frequency accuracy (Tables 2 and 3)', 'The 6060A RF OUTPUT (+7 dBm) to the 96270A rear 300 MHz Counter BNC; the 6060A rear 10 MHz IN/OUT to the lab GPS 10 MHz, REF EXT (the '
                'document applies the counter\'s reference, 4.1.6); the 96270A on the same GPS 10 MHz. 399.99999 and 499.99999 MHz are above the counter\'s range: typed from the lab\'s own counter.', 'FCORF')
    for tbl, mhzs in (('Table 2', TABLE2_MHZ), ('Table 3', TABLE3_MHZ)):
        for mhz in mhzs:
            if mhz > COUNTER_MAX_MHZ:                                   # owner 2026-11-04: above the 96270A counter's range, typed from the lab's own counter
                add(s, f'4.1 {tbl}', tag=f'{mhz} MHz', func='FREQ', meas='manual', description=f'Frequency {mhz} MHz ({tbl}, typed)',
                    nominal=num(mhz * D(10) ** 6), low=f((mhz - COUNT_STEP_MHZ) * D(10) ** 6), high=f((mhz + COUNT_STEP_MHZ) * D(10) ** 6), unit='Hz',
                    manual_prompt=(f'Set the 6060A to {mhz} MHz, RF ON, with REF EXT on the GPS 10 MHz. Read its RF OUTPUT on a frequency counter that is also on the GPS 10 MHz '
                                   f'and type the frequency in Hz (limits {hz_text((mhz - COUNT_STEP_MHZ) * D(10) ** 6)} to {hz_text((mhz + COUNT_STEP_MHZ) * D(10) ** 6)} Hz). Switch RF OFF afterwards.'),
                    flags=[f'Typed reading (owner, 2026-11-04): above the 96270A frequency counter\'s specified range (0.9 to 310 MHz, 96000 Series Product Specifications), so the '
                           'technician reads it on the lab\'s own counter. Printed limits +/-0.00001 MHz (10 Hz).'])
                continue
            add(s, f'4.1 {tbl}', tag=f'{mhz} MHz', func='FREQ', meas='fco_freq', description=f'Frequency {mhz} MHz ({tbl})', gen=dict(freq_mhz=num(mhz), level_dbm=FCO_LEVEL_DBM),
                fco=dict(range=FCO_RANGE_HIGH, gate_s=FCO_GATE_RF_S),
                nominal=num(mhz * D(10) ** 6), low=f((mhz - COUNT_STEP_MHZ) * D(10) ** 6), high=f((mhz + COUNT_STEP_MHZ) * D(10) ** 6), unit='Hz',
                flags=[UNV + ' (53132A counter -> ' + FCO + ', range 300 MHz @ 50 ohm, 20 s gate).', 'The printed limits are +/-0.00001 MHz (10 Hz); a 20 s gate shows 9 / 10 digits (1 Hz at '
                       '100 to 300 MHz; the 2 s gate showed 10 Hz steps on the bench, 2026-11-04) and the counter is specified to the reference accuracy + 0.5 count. The document does not give a level: the program sets +7 dBm (the counter needs '
                       '0.5 V pk-pk, about -2 dBm into 50 ohm).'])

    # 4.2 amplitude
    s = section('G-4.2a', 'Amplitude: power meter (Table 4)', f'{fname(LOW_MHZ)}: the 8902A with the 11722A sensor module; 250 and 520 MHz: the NRP40T on the 96270A. 13, 10 and 0 dBm at each frequency.', 'RXPWR')
    for fm in TABLE4_FREQS:
        for dbm, lo, hi in TABLE4_LEVELS:
            nm = fname(fm)
            if fm < 1:
                kw = dict(meas='level_rx', group='RXPWR', rx=dict(freq_mhz=fm, mode='power'), flags=[UNV + ' (E4418B + 8482A -> 8902A RF power with the 11722A sensor module).', MOVED],
                          moved_from=fname(DOC_LOW_MHZ))
            else:
                kw = dict(meas='level_pm', group='PM', zero_key=f'G@{fm:g}', band_label=nm, pm=dict(freq_mhz=fm), flags=[UNV + ' (E4418B + 8482A -> NRP40T on the 96270A).',
                                                                                                                     'UNVERIFIED: Rohde & Schwarz NRP40T on the 96270A power-meter mode.'])
            if dbm == 0:
                kw['flags'] = kw['flags'] + ['The document also asks to record the power-meter indication and the TI frequency at 0 dBm (the MMR Ext RF Atten value): the 8902A tuned level of Table 5 needs no such offset, so only the reading is kept.']
            add(s, '4.2 Table 4', tag=f'{nm} {lvl(dbm)} dBm', func='LEVEL', description=f'Level {lvl(dbm)} dBm at {nm} (Table 4)', gen=dict(freq_mhz=num(fm), level_dbm=dbm), nominal=float(dbm), low=f(D(lo)), high=f(D(hi)), unit='dBm', **kw)
    for fm in TABLE5_FREQS:
        nm = fname(fm)
        s = section(f'G-4.2b-{fm:g}', f'Amplitude: tuned RF level at {nm} (Table 5)', f'8902A tuned RF level at {nm}: the 0 dBm reading is the reference, each lower level is compared with it (limits are relative, +/-2.5 dB). '
                    'Keep the 6060A level unchanged while the 8902A recalibrates.', 'RX')
        ref0 = None
        for lv in TABLE5_LEVELS:
            tag = f'{nm} {lvl(lv)} dBm'
            flags = [UNV + ' (N5530SE26 microwave measurement receiver tuned RF level -> 8902A tuned RF level).']
            moved = dict(moved_from=fname(DOC_LOW_MHZ)) if fm == TUNED_LOW_MHZ else {}
            if moved:
                flags.append(MOVED_TUNED)
            if lv == 0:
                add(s, '4.2 Table 5', tag=tag + ' reference', func='LEVEL', meas='level_rx', description=f'Reference level 0 dBm at {nm} (recorded; Table 5 is relative to it)', gen=dict(freq_mhz=num(fm), level_dbm=0), rx=dict(freq_mhz=fm, mode='tuned'),
                    nominal=0.0, low=-140.0, high=5.0, unit='dBm', flags=flags + ['Record only: the document gives this row as "Reference" with no limit; the wide limits only reject an impossible reading. The Table 5 limits are judged on the relative rows.'], **moved)
                ref0 = f'4.2 Table 5 {tag} reference'
                continue
            m = add(s, '4.2 Table 5', tag=tag, func='LEVEL', meas='level_rx', description=f'Level {lv:+g} dBm at {nm} (recorded)', gen=dict(freq_mhz=num(fm), level_dbm=lv), rx=dict(freq_mhz=fm, mode='tuned'),
                    nominal=float(lv), low=-140.0, high=5.0, unit='dBm', flags=flags + ['Record only: the limit is on the relative row that follows (this reading minus the 0 dBm reference).'], **moved)
            add(s, '4.2 Table 5', tag=tag + ' relative', func='LEVEL_REL', meas='derived', description=f'Level {lv:+g} dBm at {nm} relative to the 0 dBm reference (Table 5)',
                derive=dict(kind='section', inputs=[ref0, m['ref']], constant=0), band_label=nm, zero_key=None, nominal=float(lv), low=f(D(lv) - TABLE5_TOL), high=f(D(lv) + TABLE5_TOL), unit='dB',
                flags=['Limit: the applied level +/-2.5 dB, relative to the 0 dBm reference (Table 5).'] + ([MOVED_TUNED] if moved else []), **moved)

    # 4.3 internal modulation source
    s = section('G-4.3', 'Internal modulation source', f'RF OUTPUT to the 8902A RF INPUT. {MOD_CARRIER_MHZ} MHz, +{MOD_LEVEL_DBM} dBm, INT AM 90 %, 1 kHz then 400 Hz; the 8902A audio frequency counter reads the modulation rate.', 'RX')
    for hz, lo, hi in ((1000, 950, 1050), (400, 380, 420)):
        add(s, '4.3', tag=f'{hz} Hz', func='MODRATE', meas='mod_rate', description=f'Modulation rate {hz} Hz (INT AM 90 %, {MOD_CARRIER_MHZ} MHz, +{MOD_LEVEL_DBM} dBm)',
            gen=dict(freq_mhz=MOD_CARRIER_MHZ, level_dbm=MOD_LEVEL_DBM, am=dict(pct=90, src='int', rate_hz=float(hz))), rx=dict(source='am'), nominal=float(hz), low=float(lo), high=float(hi), unit='Hz',
            flags=[UNV + ' (MMR Mod Rate -> 8902A audio frequency counter, S1).', f'The document recalls stored state 9,8 and gives no carrier: {MOD_CARRIER_MHZ} MHz is used.'])

    # 4.4 AM depth and distortion
    for fm in TABLE4_FREQS:
        nm = fname(fm)
        s = section(f'G-4.4-{fm:g}', f'AM depth and distortion at {nm} (Tables 6 and 7)', f'RF OUTPUT to the 8902A RF INPUT. {nm}, +{AM_LEVEL_DBM} dBm, INT AM. 8902A: (peak+ and peak-)/2 detector, 300 Hz to 3 kHz.', 'RX')
        for rate, rows, tbl in ((1000, TABLE6, 'Table 6'), (400, TABLE7, 'Table 7')):
            for pct, lo, hi in rows:
                hp = 1 if rate == 400 else 2                                  # owner bench 2026-11-03: the 300 Hz high-pass cut the 400 Hz tone (26.6 % for 30 %); 400 Hz rate -> 50 Hz (H1)
                flags = [UNV + (' (MMR AM depth, peak +/-/2, HP 300 Hz, LP 3 kHz -> 8902A detector D9, H2, L1).' if hp == 2 else
                                ' (MMR AM depth, peak +/-/2, LP 3 kHz -> 8902A detector D9, H1, L1).'),
                         *(['High-pass 50 Hz (H1), not 300 Hz: the 300 Hz filter attenuates the 400 Hz modulation (owner bench 2026-11-03: 30 % read 26.63 %, 70 % read 61.8 %).'] if hp == 1 else [])]
                moved = dict(moved_from=fname(DOC_LOW_MHZ)) if fm == LOW_MHZ else {}
                if moved:
                    flags.append(MOVED + ' UNVERIFIED on the bench: the 8902A keyed-in tuning at exactly 150 kHz (0.15MZ; 0.1MZ gave error 10 / 20 on 2026-11-02).')
                add(s, f'4.4 {tbl}', tag=f'{nm} {pct} % at {rate} Hz', func='AMDEPTH', meas='am_depth', description=f'AM depth {pct} % at {rate} Hz rate, {nm} ({tbl})',
                    gen=dict(freq_mhz=num(fm), level_dbm=AM_LEVEL_DBM, am=dict(pct=pct, src='int', rate_hz=float(rate))), rx=dict(detector=9, hp=hp, lp=1), nominal=float(pct), low=f(D(lo)), high=f(D(hi)), unit='%', flags=flags, **moved)
                if rate == 1000 and pct == 50:
                    add(s, f'4.4 {tbl}', tag=f'{nm} 50 % THD', func='THD', meas='thd', description=f'AM distortion, 50 % at 1 kHz, {nm}, limit < 5 % ({tbl})',
                        gen=dict(freq_mhz=num(fm), level_dbm=AM_LEVEL_DBM, am=dict(pct=50, src='int', rate_hz=1000.0)), rx=dict(source='am', tone_hz=1000), nominal=0.0, low=0.0, high=AM_THD_MAX, strict_high=True, unit='%',
                        flags=[UNV + ' (MMR distortion with HP and LP filters None -> 8902A audio distortion function, S2 at 1 kHz).'] + ([MOVED] if moved else []), **moved)

    # 4.5 FM calibration
    s = section('G-4.5', 'FM calibration (Table 8)', f'RF OUTPUT to the 8902A RF INPUT. +{FM_LEVEL_DBM} dBm, INT FM at 1 kHz; 8902A FM deviation, peak+, 300 Hz to 3 kHz.', 'RX')
    for fm, rows in TABLE8:
        nm = fname(fm)
        for dev, lo, hi in rows:
            if dev * 1000 > rx_fm_max_dev_hz(fm):                       # owner 2026-11-04: "remove all fm test points that can't be done on the 8902"
                continue
            add(s, '4.5 Table 8', tag=f'{nm} {dev} kHz', func='FMDEV', meas='fm_dev', description=f'FM deviation {dev} kHz at {nm} (INT FM 1 kHz, +{FM_LEVEL_DBM} dBm)',
                gen=dict(freq_mhz=num(fm), level_dbm=FM_LEVEL_DBM, fm=dict(khz=float(dev), src='int', rate_hz=1000.0)), rx=dict(detector=1, hp=2, lp=1), nominal=float(dev * 1000), low=f(D(lo) * 1000), high=f(D(hi) * 1000), unit='Hz',
                flags=[UNV + ' (MMR FM deviation, HP 300 Hz, LP 3 kHz -> 8902A detector D1 peak+, H2, L1).', 'UNVERIFIED: the detector is not printed; peak+ is used.'] + (['UNVERIFIED: the Instruction Manual limits FM deviation to 99.9 kHz (Table 2-5, p. 2-21); the document (Table 1) gives the 6060A/AN 1 to 500 kHz, and the owner asked for the larger deviations (2026-11-02). The command is sent as FM<kHz>KZ and read back; the unit\'s own range error stops the point if it refuses.'] if dev > 99.9 else []))

    # 4.6 deviation meter: the 96270A (FM instrument) replaces the document's E8257D + receiver; the technician types the 6060A's own Modulation Display reading
    for tno, tb in ((9, TABLE9), (10, TABLE10)):
        s = section(f'G-4.6-T{tno}', f'Deviation meter, {tb["range_khz"]} kHz range (Table {tno})',
                    f'SPCL 6,1 and the {tb["range_khz"]} kHz deviation range (400/1000 switch). The 96270A FM output (+{DEVM_LEVEL_DBM} dBm) goes to the 6060A DEVIATION METER INPUT; the program sets its carrier, rate and deviation, '
                    'and the technician types the 6060A Modulation Display deviation in kHz.', 'DEVM')
        for fm in tb['freqs']:
            for rate in tb['rates']:
                for dev in tb['devs']:
                    star = rate == 4000
                    add(s, f'4.6 Table {tno}', tag=f'{fm} MHz {rate} Hz {dev} kHz', func='DEVMETER', meas='devmeter', description=f'Deviation meter {fm} MHz, rate {rate} Hz, {dev} kHz deviation: 6060A display (kHz, Table {tno})',
                        fmsrc=dict(carrier_mhz=float(fm), level_dbm=DEVM_LEVEL_DBM, dev_khz=float(dev), rate_hz=float(rate)),
                        nominal=float(dev), low=float(dev - tb['limit']), high=float(dev + tb['limit']), unit='kHz',
                        manual_prompt=(f'The 96270A is sending {fm} MHz, +{DEVM_LEVEL_DBM} dBm, FM {dev} kHz deviation at {rate} Hz (output ON). On the 6060A ({tb["range_khz"]} kHz range, SPCL 6,1) read the '
                                       f'Modulation Display deviation and type it in kHz. Limit: {dev} kHz +/-{tb["limit"]} kHz.'),
                        flags=['UNVERIFIED: the document applies the signal from an E8257D through a splitter and judges the 6060A display against a microwave measurement receiver; here the 96270A FM output is the reference '
                               '(its FM accuracy is not read from the Remote Programmers Manual), so the limit is the set deviation +/- the printed limit. The 6060A display is typed.',
                               'UNVERIFIED: the 96270A FM commands (INST FM, FM:STAT, FM:DEV in Hz, FM:INT:FREQ in Hz) were read on pages 32, 35, 36, 38 and 59 of the Remote Programmers Manual; nothing has run on hardware.'] +
                              (['Footnote *: the document\'s receiver filters were 300 Hz and 15 kHz at the 4 kHz rate; not applicable with the 96270A as the reference.'] if star else []) +
                              (['The 96270A limits FM deviation to 300 kHz at 9 to 31.4375 MHz and to 0.12 % of the carrier above 125.75 MHz (Operator Manual Table 3-26): this point is listed as NOT TESTED.'] if dev * 1000 > fm_limit_hz(fm) else []))

    # 4.7 spectral purity
    s = section('G-4.7a', 'Spectral purity: harmonics (Table 11)', f'RF OUTPUT to the 8563E RF INPUT. +{HARM_LEVEL_DBM} dBm, spectrum analyzer input attenuation 40 dB in the document (the program sets its own range). Harmonics at the first four harmonic signals.', 'SA')
    for mhz, lim in TABLE11:
        add(s, '4.7 Table 11', tag=f'harmonics {mhz:g} MHz', func='HARMONIC', meas='harmonic', description=f'Harmonics 2 to {HARM_COUNT} at {fname(mhz)}, +{HARM_LEVEL_DBM} dBm (worst, dBc, limit < {lim} dBc)',
            gen=dict(freq_mhz=num(mhz), level_dbm=HARM_LEVEL_DBM), sa=dict(n_max=HARM_COUNT), nominal=float(lim), low=-200.0, high=float(lim), strict_high=True, unit='dBc',
            flags=[UNV + ' (E4440A harmonic distortion measurement -> software harmonic search on the 8563E).',
                   'UNVERIFIED reading of "first four Harmonic signals": harmonics 2 to 4 are measured (the Instruction Manual procedure does the same). The analyzer settings are this procedure\'s choice.'] +
                  (['10 kHz is below the 0.1 MHz the 6060A driver programs (p. 2-15): the point is listed as NOT TESTED.'] if mhz < 0.1 else []))
    s = section('G-4.7b', 'Spectral purity: spurious (Table 12)', 'RF OUTPUT to the 8563E RF INPUT. The carrier level is as the table footnotes say (13 dBm, then 0 dBm at *, then 1 dBm at **).', 'SA')
    for spur, carrier, dbm in TABLE12:
        smhz = D(spur)
        off_hz = abs(smhz - D(str(carrier))) * D(10) ** 6
        base = dict(tag=f'spur {spur} MHz carrier {carrier:g} MHz {dbm:+d} dBm', func='SPUR', description=f'Spur at {spur} MHz, carrier {carrier:g} MHz {dbm:+d} dBm (limit < {SPUR_LIMIT_DBC} dBc)', nominal=float(SPUR_LIMIT_DBC),
                    low=-200.0, high=float(SPUR_LIMIT_DBC), strict_high=True, unit='dBc')
        if off_hz < 1000:
            add(s, '4.7 Table 12', meas='manual', group='SA', nominal=base['nominal'], low=-200.0, high=base['high'], strict_high=True, unit='dBc', tag=base['tag'], func='SPUR', description=base['description'] + ' (typed)',
                manual_prompt=(f'Carrier {carrier:g} MHz at {dbm:+d} dBm' + (' (reach it from 242 MHz upward in 1 MHz steps: set directly it can show UNCAL)' if approach(carrier) else '')
                               + '. Narrow the analyzer (RBW 10 to 30 Hz) and read the spur at {spur} MHz ({float(off_hz):g} Hz from the carrier); type its level relative to the carrier in dBc (limit < {SPUR_LIMIT_DBC} dBc).'),
                flags=['Typed reading: a spur this close to the carrier cannot be separated from it with the 8563E settings the program uses (UNVERIFIED that the analyzer can resolve it at all).'])
            continue
        near = off_hz <= 1000000
        sa = dict(kind='off', target_hz=float(off_hz)) if near else dict(kind='abs', target_hz=float(smhz * D(10) ** 6))
        steps = approach(carrier)
        gen = dict(freq_mhz=num(carrier), level_dbm=dbm, am=None, **({'approach_mhz': steps} if steps else {}))
        add(s, '4.7 Table 12', meas='spur', gen=gen, sa=sa, **base,
            flags=([APPROACH_NOTE] if steps else []) + [UNV + ' (E4440A -> 8563E).', ('Read as an OFFSET from the carrier (both sides, the worse is taken; UNVERIFIED reading of the table: the document lists absolute frequencies, one side).' if near else
                                                 'Read as an ABSOLUTE frequency.'), 'The analyzer window, RBW and reference level are this procedure\'s choice; the reading is the highest peak in that window minus the carrier level.'])

    # 4.8 residual FM
    s = section('G-4.8', 'Residual FM', f'RF OUTPUT to the 8902A RF INPUT, {RESFM_MHZ} MHz, +{RESFM_DBM} dBm, no modulation; 8902A FM deviation, peak+.', 'RX')
    add(s, '4.8', tag='residual FM', func='RESFM', meas='fm_dev', description=f'Residual FM, {RESFM_MHZ} MHz, +{RESFM_DBM} dBm, peak, limit < {RESFM_MAX_HZ} Hz', gen=dict(freq_mhz=RESFM_MHZ, level_dbm=RESFM_DBM), rx=dict(detector=1, hp=1, lp=3),
        nominal=0.0, low=0.0, high=float(RESFM_MAX_HZ), strict_high=True, unit='Hz',
        flags=[UNV + ' (R&S FMAV modulation analyzer, +PEAK, HP 20 Hz, LP 23 kHz -> 8902A detector D1, H1 (50 Hz), L3 (>20 kHz)).',
               'The 8902A has no 20 Hz high-pass or 23 kHz low-pass: 50 Hz and >20 kHz are the nearest (UNVERIFIED; the result may differ from the FMAV\'s).'])

    # 4.9 residual AM
    s = section('G-4.9', 'Residual AM', f'RF OUTPUT to the 8902A RF INPUT, {RESFM_MHZ} MHz, +{RESAM_DBM} dBm, no modulation; 8902A AM depth, true rms.', 'RX')
    add(s, '4.9', tag='residual AM', func='RESAM', meas='am_depth', description=f'Residual AM, {RESFM_MHZ} MHz, +{RESAM_DBM} dBm, rms, limit < {RESAM_MAX_PCT} %', gen=dict(freq_mhz=RESFM_MHZ, level_dbm=RESAM_DBM), rx=dict(detector=8, hp=1, lp=2),
        nominal=0.0, low=0.0, high=RESAM_MAX_PCT, strict_high=True, unit='%',
        flags=[UNV + ' (FMAV AM, RMS -> 8902A detector D8, 50 Hz to 15 kHz).', 'The document does not repeat the frequency: 520 MHz (left by 4.8) is used. Table 1 states the same limit as < -60 dBc.'])

    return dict(
        schema=1, kind='rf-generator-pv', model='6060A',
        source=dict(cite=f'{DOC}, Calibration Procedure for Synthesized Signal Generator 6060 A/AN (Fluke), 30 April 2017 (GIDEP)', limits_text='GIDEP T.O. 33K3-4-911-1 (Fluke 6060A/AN)',
                    note='Points and limits are the document\'s own tables. Its measuring instruments (53132A, E4418B + 8482A, N5530SE26, E4440A, E8257D, FMAV) are replaced by the lab bench (8902A, 96270A + NRP40T and its frequency counter, 8563E); '
                         'each replacement is flagged UNVERIFIED on the point. The Calibration Performance Table is "Not Required"; Appendix A (reference oscillator adjustment) is not built.'),
        options=dict(count_resolution_hz=COUNT_RES_HZ, fm_max_khz=FM_MAX_KHZ, checkpoint_requires_ref=True),     # points were renumbered on 2026-11-03: a saved result must name its point
        constants=dict(harm_count=HARM_COUNT),
        discrepancies=[
            'The document measures with instruments this bench does not have; the 8902A, 96270A + NRP40T and 8563E replace them (see the flags). The reference-oscillator frequency (4.1.5) and the frequency points up to 300 MHz (Tables 2 and 3) are read on the 96270A frequency counter (on the GPS 10 MHz); 399.99999 and 499.99999 MHz are above its range and are typed. The deviation-meter checks (4.6) use the 96270A FM output as the source and the 6060A display is typed.',
            'Table 8: the 50 kHz deviation on the 250 kHz carrier is not tested: it is above the 8902A\'s specified 40 kHz peak deviation for 250 kHz to 10 MHz carriers (p. 1-20), and the owner removed the FM points the 8902A cannot measure (2026-11-04).',
            'Table 2 prints 100.00000 to 199.99999 MHz in steps of 11.11111 MHz; the last row is printed 199.99999 (not 199.99999 + rounding): used as printed.',
            'Spur frequencies of Table 12 are printed as absolute frequencies; those within 1 MHz of the carrier are measured as offsets (both sides), those within 1 kHz are typed.',
            'The document recalls stored state 9,8 in 4.3 and gives no carrier for 4.3, 4.9; 300 MHz and 520 MHz are used.',
            'Tables 4, 6 and 7: the document\'s 100 kHz carrier is moved to 150 kHz (owner, 2026-11-03), where the 8902A RF input range starts; the 6060A between 100 and 150 kHz is not verified.',
            'Table 5: the document\'s -127 dBm row is left out at every carrier (owner, 2026-11-03: "delete the -127db test points...stop at -120dB"); the levels end at -120 dBm.',
            'Table 5: the document\'s 100 kHz carrier is moved to 2.5 MHz (owner, 2026-11-03), where the 8902A tuned RF level starts (error 20 at 150 kHz); the 6060A level below 2.5 MHz is not verified by Table 5.',
            'Table 1 also lists display range, amplitude, internal modulation, AM / FM accuracy, deviation meter, spectral purity and residual AM / FM: each is covered by a test above; the 96270A counter readings cover the display range (+/-1 count).'],
        sections=sections)


def main():
    spec = build_spec()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(s['points']) for s in spec['sections'])
    print(f'wrote {OUT.name}: {n} points in {len(spec["sections"])} sections')


if __name__ == '__main__':
    main()
