"""Fluke 6060A / AN RF signal generator over GPIB (IEEE-488 option), driven in the 6060A's own two-letter command language (it has NO SCPI and no *IDN?).

Source: "6060A/AN Synthesized Signal Generator Instruction Manual", Section 2 (printed pp. 2-27 to 2-64) and Section 4A (attenuator sections); read from rendered page
images. Every Cmd below carries its page. What the manual does not print is NOT guessed: it is verified=False in COMMANDS and listed in the report. The main ones:
    * the TEXT layout of the IR / IU / IO / II / IM replies (the table shows octal fields "AAAAA,BBBBB,CCCCC" in one place and three 3-digit groups in another);
      the driver takes every digit group in the reply and reads each as an octal field, so either layout works,
    * whether the RF bit of the learn string (LM99, Fig. 2-7, p. 2-50) really follows the RF OUTPUT state (the printed preset memory 98 shows RF = 0 although the generator
      powers up with RF on): the driver confirms RF OFF from it, so a wrong polarity would show up as a refused read-back, never as a silent wrong state,
    * that RO0 / RO1 keep an alternate attenuator section chosen with SP83..SP86,
    * the low-rate FM option -651 (IO second field, 8 = -651): its FM resolution digit (the manual only says the quantity then has 0.1 Hz resolution),
    * the volts <-> dBm conversion used when the display is in volts (50 ohm, 0 dBm = 223.6 mV): the driver only ever programs dBm, a volts display is refused.
Printing note: the learn string printed for memory 98 on p. 2-46 reads "...BBOBKKAAAAAPECEAABPE..."; Fig. 2-7 (p. 2-49) shows chars 25 to 32 as "BBOBKDAA"
(300,000,000 Hz) and only that spelling gives a valid checksum (the pairs add up to 01). The tests use the checksum-correct string.

Language facts used (Section 2):
  * Address: 5 rear-panel switches, no factory default printed (the owner's lab address is DEFAULT_ADDRESS, given to the constructor / connect(), never fixed in code).
    Commands: HEADER (2 letters) [+ number] [+ suffix]; several in one message are separated by ',' or ';'. This driver sends ONE command per write so every write
    is logged and checked on its own. The record terminator is LF (TM0, the power-on value). A syntax error discards the rest of its message.
  * There is NO query for frequency, level or modulation. The only read-back is the 64-letter learn string LM99 (letters A..P = hex 0..F): decode_learn() below.
  * Settling: VM1 (valid mode) makes the generator hold the NEXT message until the RF output is valid (45 ms after any hardware change, p. 2-55), so a read-only query sent
    after a write is answered when the output has settled (default 'vm'). The other method is SM16 (output-valid SRQ) + serial poll ('srq').
  * IR (rejected entries) CLEARS what it reports, so it is asked exactly once per group of writes and never retried. UNCAL codes come from IU.
  * Device clear (and CL) re-establishes RC98, RO1 (RF ON at the preset -10 dBm) and the default modes; connect() therefore sends RO0 straight after the clear.
Writes are sent once and never retried; each setter reads LM99 back and compares. Only read-only queries (ID, LM99, IO, II) may be retried. The RF output goes to RO0 at the
end of every point (end_point()) and at cleanup. There is no calibration (adjustment) command in this driver.
"""
from __future__ import annotations

import math
import re
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError
from .gpib_address import address_of, check_address, retarget, serial_poll

UM = '6060A/AN Instruction Manual'
MIN_MHZ, MAX_MHZ = 0.1, 1050.0           # p. 2-15
MIN_DBM, MAX_DBM = -137.0, 13.0          # calibrated range (p. 2-15); -147.4 .. +19 is UNCAL
UNCAL_MIN_DBM, UNCAL_MAX_DBM = -147.4, 19.0
MAX_AM_PCT = 99                          # p. 2-21 (> 90 % is UNCAL)
MAX_FM_KHZ, MAX_FM_KHZ_651 = 99.9, 9.99  # p. 2-21 / Table 2-5 (-651 low-rate FM)
MOD_RATES = {400: '0', 1000: '1'}        # MR0 / MR1 (p. 2-21)
SECTION_LEVEL_DBM = {0: 12.0, 1: 6.0, 2: 0.0, 3: -12.0}      # Fig. 4A-2: AP12DB, AP6DB, AP0DB, AP-12DB (the instrument picks sections 0 to 3 itself)
ALT_SECTION_CODE = {4: '83', 5: '84', 6: '85', 7: '86'}      # SP83..SP86 after AP-12DB (p. 2-34, p. 4A-5)
ALT_SECTION_LEVEL_DBM = -12.0            # valid -17.0 .. -11.1 dBm with AM off (p. 4A-5)
VALID_STB = 16                           # serial poll bit: output valid (Table 2-18, p. 2-60)


def _r(topic, page):
    return f'{UM}: {topic} (p. {page})'


def _ph_enum(*values, sample=None):
    return Placeholder('enum', '', sample if sample is not None else values[0], enum=tuple(values))


def _f(fmt, sample):
    return Placeholder('float', fmt, sample)


COMMANDS = {
    # ---- reset / status plumbing (never overridable) ----------------------------------------------------------------------------------------------------
    'reset': cmdreg.reset_cmd(True, _r('RC98 = Instrument Preset State (same as [RCL][9][8])', '2-20 and 2-62'), template='RC98',
                              note='Recalls memory 98: 300 MHz, -10 dBm, all modulation off. It does NOT change the RF ON / OFF state or the interface modes: both are set again afterwards'),
    'status.clear': Cmd('CE', 'Clear rejected-entry status', 'Clears the rejected-entry status (never overridable)', kind='set', risk='locked', verified=True, ref=_r('CE', '2-53')),
    'id': Cmd('ID', 'Identify', 'Answers "6060A" (never overridable: the model check of every connect)', kind='query', risk='locked', verified=True, ref=_r('ID', '2-32')),
    'ir.query': Cmd('IR', 'Rejected entries', 'Rejected-entry codes. READING CLEARS THEM, so it is asked once per group of writes and never retried. The text layout of the reply is UNVERIFIED '
                    '(octal fields "AAAAA,BBBBB,CCCCC" or three 3-digit groups): every digit group is read as one octal field (never overridable)',
                    kind='query', risk='locked', verified=False, ref=_r('IR, Table 2-6', '2-32 and 2-25')),
    'iu.query': Cmd('IU', 'UNCAL codes', 'UNCAL codes (Table 2-5). The reply layout is UNVERIFIED (same remark as IR); the third field 400 is "RF output off"',
                    kind='query', verified=False, ref=_r('IU, Table 2-5', '2-32 and 2-25')),
    'io.query': Cmd('IO', 'Options installed', 'Three integers; the second is the sum 1 = -570, 2 = -131, 4 = -130, 8 = -651 (low-rate FM). The reply layout is UNVERIFIED',
                    kind='query', verified=False, ref=_r('IO', '2-32')),
    'ii.query': Cmd('II', 'Interface modes', 'The interface modes as a number: TM 1, RM 2, VM 4, UM 8, EM 16. The reply layout (a 5-digit integer) is UNVERIFIED',
                    kind='query', verified=False, ref=_r('II, Table 2-13', '2-32 and 2-54')),
    'im.query': Cmd('IM', 'SRQ mask', 'The SRQ mask (sum of the reasons of Table 2-18); reply layout UNVERIFIED', kind='query', verified=False, ref=_r('IM', '2-33 and 2-60')),
    'lm.query': Cmd('LM{mem}', 'Learn string', 'Learn Memory: 64 letters A..P (hex 0..F) + end of record. LM99 is the present instrument state, LM98 the preset. This is the only read-back '
                    'the 6060A has (decode_learn)', placeholders={'mem': Placeholder('int', '', 99)}, kind='query', verified=True, ref=_r('LM, Fig. 2-7', '2-45 to 2-52')),
    'xa.query': Cmd('XA', 'Hardware attenuation', 'Monitor command: the attenuation in use as an integer 0 to 23 (units of 6 dB). Diagnostics only, output not guaranteed; the reply is UNVERIFIED',
                    kind='query', verified=False, ref=_r('XA', '2-34 and 2-59')),
    # ---- interface modes / SRQ ------------------------------------------------------------------------------------------------------------------------------
    'modes.set': Cmd('@{n}', 'Interface modes', 'Sets all five interface modes at once as a sum: TM 1 (CR terminator), RM 2, VM 4 (valid mode), UM 8, EM 16; 4 = LF terminator, VM1 only. '
                     'Read back with II', placeholders={'n': Placeholder('int', '', 4)}, kind='set', readback='ii.query', verified=True, ref=_r('interface modes', '2-54')),
    'sm.set': Cmd('SM{mask}', 'SRQ mask', 'Sum of the reasons: 1 ready, 2 rejected entry, 4 uncalibrated, 8 power on, 16 output valid, 128 front panel', placeholders={'mask': Placeholder('int', '', 16)},
                  kind='set', readback='im.query', verified=True, ref=_r('SM, Table 2-18', '2-33 and 2-60')),
    # ---- the output ---------------------------------------------------------------------------------------------------------------------------------------------
    'ro.on': Cmd('RO1', 'RF output on', 'Enables the RF output (never overridable)', kind='set', readback='lm.query', risk='output', verified=True, ref=_r('RO', '2-23 and 2-34')),
    'ro.off': Cmd('RO0', 'RF output off', 'Disables the RF output: the only RF-off command (never overridable)', kind='set', readback='lm.query', risk='output', verified=True,
                  ref=_r('RO', '2-23 and 2-24')),
    'fr.set': Cmd('FR{mhz:.5f}MZ', 'Frequency', 'Output frequency in MHz, 0.1 to 1050 MHz, 10 Hz resolution (245 MHz and 512 MHz are band-ranging points)',
                  placeholders={'mhz': _f('.5f', 100.0)}, kind='set', readback='lm.query', verified=True, ref=_r('FR', '2-15, 2-31, 2-36')),
    'ap.set': Cmd('AP{dbm:.1f}DB', 'Amplitude (dBm)', '-137 to +13 dBm calibrated, 0.1 dB resolution (-147.4 to -137.1 and +13.1 to +19 are UNCAL)',
                  placeholders={'dbm': _f('.1f', 0.0)}, kind='set', readback='lm.query', verified=True, ref=_r('AP', '2-15 and 2-30')),
    'ai.set': Cmd('AI{state}', 'Internal AM', '1 = on, 0 = off', placeholders={'state': _ph_enum(0, 1)}, kind='set', readback='lm.query', verified=True, ref=_r('AI', '2-21, 2-33')),
    'ae.set': Cmd('AE{state}', 'External AM', '1 = on, 0 = off (EXT HI / LO show +/-2 % of the nominal 1 V peak input)', placeholders={'state': _ph_enum(0, 1)}, kind='set',
                  readback='lm.query', verified=True, ref=_r('AE', '2-21, 2-22, 2-33')),
    'fi.set': Cmd('FI{state}', 'Internal FM', '1 = on, 0 = off', placeholders={'state': _ph_enum(0, 1)}, kind='set', readback='lm.query', verified=True, ref=_r('FI', '2-21, 2-33')),
    'fe.set': Cmd('FE{state}', 'External FM', '1 = on, 0 = off. Table 2-8 prints FE, the front-panel summary page has a smudged glyph for this header (UNVERIFIED)',
                  placeholders={'state': _ph_enum(0, 1)}, kind='set', readback='lm.query', verified=False, ref=_r('FE', '2-33 (smudged on 2-21)')),
    'am.set': Cmd('AM{pct:.0f}PC', 'AM depth', 'Percent, 0 to 99, 1 % resolution; above 90 % with AM on is UNCAL, outside 0 to 99 is rejected', placeholders={'pct': _f('.0f', 30.0)},
                  kind='set', readback='lm.query', verified=True, ref=_r('AM', '2-21, 2-22, 2-33')),
    'fm.set': Cmd('FM{khz:.9g}KZ', 'FM deviation', 'kHz, 0.1 to 99.9 (0 to 9.99 with option -651), 3 digits. UNCAL when FM is on and the deviation is below 100 Hz (10 Hz with -651) or '
                  'above (frequency - 100 kHz)/3', placeholders={'khz': _f('.9g', 5.0)}, kind='set', readback='lm.query', verified=True, ref=_r('FM', '2-21, 2-22')),
    'mr.set': Cmd('MR{rate}', 'Internal modulation rate', '0 = 400 Hz, 1 = 1000 Hz (internal AM and FM share it)', placeholders={'rate': _ph_enum('0', '1', sample='1')}, kind='set',
                  readback='lm.query', verified=True, ref=_r('MR', '2-21, 2-22, 2-33')),
    'sp.section': Cmd('SP{code}', 'Alternate attenuator section', '83, 84, 85, 86 select the alternate 24 dB attenuators of sections 4, 5, 6, 7 after AP-12DB (AM off). It turns off relative modes, '
                      'fixed range and ALL modulation and turns RF and level correction on; any new amplitude entry restores the default attenuators',
                      placeholders={'code': _ph_enum('83', '84', '85', '86')}, kind='set', readback='lm.query', verified=True, ref=_r('SP83..SP86, Fig. 4A-2', '2-34, 4A-5')),
    # ---- step sizes and steps (p. 2-26, 2-27, 2-35) --------------------------------------------------------------------------------------------------------
    'fs.set': Cmd('FS{mhz:.5f}MZ', 'Frequency step size', 'Only stores the step size (it does not select the step function), 0 to 1050 MHz', placeholders={'mhz': _f('.5f', 1.0)}, kind='set',
                  readback='lm.query', verified=True, ref=_r('FS', '2-26, 2-27, 2-35')),
    'ls.set': Cmd('LS{db:.1f}DB', 'Amplitude step size', 'dB, 0 to 166 dB, 0.1 dB resolution', placeholders={'db': _f('.1f', 1.0)}, kind='set', readback='lm.query', verified=True,
                  ref=_r('LS', '2-26, 2-35')),
    'ps.set': Cmd('PS{pct:.0f}PC', 'AM step size', 'Percent, 0 to 99', placeholders={'pct': _f('.0f', 1.0)}, kind='set', readback='lm.query', verified=True, ref=_r('PS', '2-27, 2-35')),
    'ds.set': Cmd('DS{khz:.9g}KZ', 'FM step size', 'kHz, 0 to 99.9 (9.99 with -651)', placeholders={'khz': _f('.9g', 0.1)}, kind='set', readback='lm.query', verified=True,
                  ref=_r('DS', '2-26, 2-35')),
    'fu': Cmd('FU', 'Step frequency up', 'Selects frequency as the step function AND steps once by the FS size', kind='set', readback='lm.query', verified=True, ref=_r('FU', '2-27, 2-35')),
    'fd': Cmd('FD', 'Step frequency down', 'As FU, downwards', kind='set', readback='lm.query', verified=True, ref=_r('FD', '2-27, 2-35')),
    'lu': Cmd('LU', 'Step amplitude up', 'One step of the LS size', kind='set', readback='lm.query', verified=True, ref=_r('LU', '2-35')),
    'ld': Cmd('LD', 'Step amplitude down', 'One step of the LS size', kind='set', readback='lm.query', verified=True, ref=_r('LD', '2-35')),
    'pu': Cmd('PU', 'Step AM up', 'One step of the PS size', kind='set', readback='lm.query', verified=True, ref=_r('PU', '2-35')),
    'pd': Cmd('PD', 'Step AM down', 'One step of the PS size', kind='set', readback='lm.query', verified=True, ref=_r('PD', '2-35')),
    'du': Cmd('DU', 'Step FM up', 'One step of the DS size', kind='set', readback='lm.query', verified=True, ref=_r('DU', '2-35')),
    'dd': Cmd('DD', 'Step FM down', 'One step of the DS size', kind='set', readback='lm.query', verified=True, ref=_r('DD', '2-35')),
}

# ---- Rejected-entry (Table 2-6, p. 2-25) and UNCAL (Table 2-5) codes: field -> {bit value (octal): meaning} ----------------------------------------------------
REJECT_BITS = (
    {0o001: 'FM deviation not between 0 and 99.9 kHz (9.99 with -651)', 0o002: 'FM step not between 0 and 99.9 kHz', 0o004: 'AM depth not between 0 and 99 %',
     0o010: 'AM step not between 0 and 99 %', 0o020: 'IEEE-488 command syntax error', 0o040: 'IEEE-488 input value out of range', 0o100: 'special function requires the IEEE option',
     0o200: 'IEEE edit or step beyond the allowed range'},
    {0o001: 'frequency not between 0.1 and 1050 MHz', 0o004: 'frequency step not between 0 and 1050 MHz', 0o040: 'invalid memory location', 0o100: 'invalid data in memory',
     0o200: 'special function not allowed'},
    {0o001: 'output amplitude not between 10 nV and 2 V', 0o002: 'insufficient resolution for units conversion', 0o004: 'units conversion to volts not allowed with reference in volts',
     0o010: 'units conversion to dB not allowed with reference in volts', 0o020: 'amplitude step not between 0 and 166 dB or 0 and 1999 V',
     0o040: 'units conversion on amplitude step not allowed', 0o100: 'amplitude step and amplitude display not in the same units'},
)
UNCAL_BITS = (
    {0o001: 'FM deviation below 100 Hz (10 Hz with -651)', 0o002: 'FM deviation above (frequency - 100 kHz)/3', 0o004: 'excess FM deviation, a PLL is unlocked', 0o020: 'AM depth above 90 %'},
    {0o010: 'main or reference PLL unlocked'},
    {0o001: 'level below the calibrated vernier range or below -137 dBm', 0o002: 'peak (AM) amplitude above +13 dBm', 0o004: 'amplitude unleveled', 0o010: 'fixed-range vernier at 0',
     0o020: 'fixed-range vernier at full scale', 0o040: 'RPP tripped', 0o100: 'level below -137 dBm', 0o200: 'level correction disabled', 0o400: 'RF output off'},
)
RF_OFF_UNCAL = 0o400                     # third field: "RF output off" is shown as an UNCAL code (Table 2-5)


def parse_fields(text: str) -> tuple:
    """Every digit group of an IR / IU reply read as one octal field (digits 8 and 9 fall back to decimal). A lone 9-digit group is split into three. -> tuple of ints."""
    groups = re.findall(r'\d+', str(text))
    if len(groups) == 1 and len(groups[0]) == 9:
        g = groups[0]
        groups = [g[0:3], g[3:6], g[6:9]]
    out = []
    for g in groups:
        try:
            out.append(int(g, 8))
        except ValueError:
            out.append(int(g))
    return tuple(out)


def describe_fields(fields, table) -> list:
    """The meanings of every bit set in the fields (field 1, 2, 3 of the table); unknown bits are shown as octal."""
    out = []
    for i, value in enumerate(fields[:3]):
        names = table[i] if i < len(table) else {}
        for bit in sorted(names):
            if value & bit:
                out.append(names[bit])
        rest = value & ~sum(names)
        if rest:
            out.append(f'field {i + 1} bits {rest:03o} (not in the table)')
    return out


# ---- the learn string (Fig. 2-7, p. 2-45 to 2-52) ------------------------------------------------------------------------------------------------------------
LEARN_LEN = 64
DATA_SET_2_PRESET = 0x1106               # bright-digit positions etc. of memory 98; the simulator keeps it constant
EXT_MOD_LEVEL = {0b00: 'valid', 0b01: 'ext_lo', 0b10: 'ext_hi', 0b11: 'invalid'}
STEP_FUNCTION = {0b001: 'freq', 0b010: 'ampl', 0b100: 'mod'}
CORRECTION = {0b00: 'all_on', 0b01: 'attenuator_off', 0b10: 'all_off'}
OHMS = 50.0                              # volts <-> dBm for a volts display (UNVERIFIED assumption)

PRESET_LEARN = 'BOABAAAAPPJMAAAKAAAAAAAABBOBKDAAAAAPECEAABPEAAABDAEEBBAGBLKKMPAC'   # LM98, checksum-correct (see the module docstring about p. 2-46)


def _nibbles(text):
    out = []
    for c in text:
        n = ord(c) - 65
        if not 0 <= n <= 15:
            raise InstrumentError(f'6060A learn string: {c!r} is not one of A..P')
        out.append(n)
    return out


def _hex(nibs, a, b, signed=False):
    """Chars a..b (1-based, inclusive) as one number."""
    value = 0
    for n in nibs[a - 1:b]:
        value = value * 16 + n
    if signed and nibs[a - 1] >= 8:
        value -= 16 ** (b - a + 1)
    return value


def _amplitude(number, res):
    """(units, dBm or None, volts or None, resolution text) of an amplitude number and its resolution digit (p. 2-52 item 2)."""
    if res in (0xA, 0xB):
        return 'dBm', number / 10.0, None
    if 0 <= res <= 9:
        volts = number * (10.0 ** res) * 1e-9
        dbm = 10.0 * math.log10(volts * volts / OHMS / 1e-3) if volts > 0 else None
        return 'V', dbm, volts
    raise InstrumentError(f'6060A learn string: amplitude resolution {res:X} is not defined')


def learn_checksum_ok(text: str) -> bool:
    """The 32 bytes (two letters each, checksum included) add up to a number ending in 01 (p. 2-52 item 6)."""
    nibs = _nibbles(text)
    return sum(nibs[i] * 16 + nibs[i + 1] for i in range(0, LEARN_LEN, 2)) % 256 == 1


def decode_learn(text: str) -> dict:
    """The present state from a 64-letter learn string (LM99). Raises InstrumentError for a wrong length, a letter outside A..P or a bad checksum.
    Keys: frequency_hz, amplitude_dbm (None when a volts display cannot be converted), amplitude_units 'dBm' | 'V', amplitude_v, am_depth_pct, am_step_pct, fm_dev_hz,
    fm_step_hz, freq_step_hz, amp_step (dB or V), rf_on, ext_ref, ext_mod_level, int_am, ext_am, int_fm, ext_fm, mod_rate_hz (400 | 1000 | None), step_function,
    rel_freq, rel_amp, mod_display ('AM' | 'FM'), correction, fixed_range, fm_res_hz."""
    text = str(text).strip().replace(' ', '').upper()
    if len(text) != LEARN_LEN:
        raise InstrumentError(f'6060A learn string has {len(text)} letters, not {LEARN_LEN}: {text!r}')
    nibs = _nibbles(text)
    if not learn_checksum_ok(text):
        raise InstrumentError(f'6060A learn string checksum is wrong: {text!r}')
    ds1, ds2 = _hex(nibs, 49, 52), _hex(nibs, 53, 56)
    units, dbm, volts = _amplitude(_hex(nibs, 9, 12, True), nibs[58])
    step_units, step_dbm, _sv = _amplitude(_hex(nibs, 13, 16, True), nibs[57])
    fm_res = 10.0 ** nibs[56]
    rate = (ds1 >> 5) & 0b11
    out = dict(
        am_depth_pct=_hex(nibs, 1, 2), am_step_pct=_hex(nibs, 3, 4),
        amplitude_units=units, amplitude_dbm=dbm, amplitude_v=volts,
        amp_step=step_dbm if step_units == 'dBm' else _hex(nibs, 13, 16, True) * (10.0 ** nibs[57]) * 1e-9,
        reference_frequency_hz=_hex(nibs, 17, 24), frequency_hz=_hex(nibs, 25, 32), freq_step_hz=_hex(nibs, 33, 40),
        fm_dev_hz=_hex(nibs, 41, 44, True) * fm_res, fm_step_hz=_hex(nibs, 45, 48, True) * 10.0 ** nibs[63], fm_res_hz=fm_res,
        ext_ref=bool(ds1 >> 15 & 1), rf_on=bool(ds1 >> 14 & 1), ext_mod_level=EXT_MOD_LEVEL[ds1 >> 12 & 0b11],
        ext_fm=bool(ds1 >> 10 & 1), int_fm=bool(ds1 >> 9 & 1), ext_am=bool(ds1 >> 8 & 1), int_am=bool(ds1 >> 7 & 1),
        mod_rate_hz={0b01: 400, 0b10: 1000}.get(rate), step_function=STEP_FUNCTION.get(ds1 >> 2 & 0b111),
        rel_freq=bool(ds1 >> 1 & 1), rel_amp=bool(ds1 & 1), mod_display='FM' if ds2 >> 4 & 1 else 'AM',
        correction=CORRECTION.get(nibs[62] >> 2 & 0b11, 'invalid'), fixed_range=((nibs[62] & 0b11) == 0b01),
        data_set_1=ds1, data_set_2=ds2, raw=text)
    return out


def encode_learn(state: dict) -> str:
    """The 64-letter learn string of a state dict (the keys decode_learn returns, plus defaults for anything missing). Used by the simulator; decode_learn(encode_learn(s))
    returns s within the resolution of the string (0.1 dBm, 10 Hz, 1 %, the FM resolution)."""
    nibs = [0] * LEARN_LEN

    def put(a, b, value):
        width = b - a + 1
        value = int(value) & (16 ** width - 1)
        for i in range(width):
            nibs[b - 1 - i] = (value >> (4 * i)) & 0xF

    s = state
    put(1, 2, s.get('am_depth_pct', 30))
    put(3, 4, s.get('am_step_pct', 1))
    put(9, 12, round(s.get('amplitude_dbm', -10.0) * 10))
    put(13, 16, round(s.get('amp_step', 1.0) * 10))
    nibs[57], nibs[58], nibs[59] = 0xB, 0xA, 0xA                  # resolution chars 58, 59, 60: 0.1 dB(m) (A or B both mean 0.1; memory 98 has B, A, A)
    put(17, 24, s.get('reference_frequency_hz', 0))
    put(25, 32, round(s.get('frequency_hz', 300e6)))
    put(33, 40, round(s.get('freq_step_hz', 1e6)))
    fm_res_digit = int(round(math.log10(s.get('fm_res_hz', 10.0))))
    put(41, 44, round(s.get('fm_dev_hz', 5000.0) / 10.0 ** fm_res_digit))
    nibs[56] = fm_res_digit                                         # char 57
    put(45, 48, round(s.get('fm_step_hz', 100.0) / 100.0))
    nibs[63] = 2                                                    # char 64: FM step resolution 100 Hz
    rate = {400: 0b01, 1000: 0b10}.get(s.get('mod_rate_hz', 1000), 0)
    ext = {v: k for k, v in EXT_MOD_LEVEL.items()}[s.get('ext_mod_level', 'valid')]
    ds1 = ((s.get('ext_ref', False) << 15) | (s.get('rf_on', True) << 14) | (ext << 12) | (s.get('ext_fm', False) << 10) | (s.get('int_fm', False) << 9)
           | (s.get('ext_am', False) << 8) | (s.get('int_am', False) << 7) | (rate << 5)
           | ({v: k for k, v in STEP_FUNCTION.items()}.get(s.get('step_function', 'freq'), 0) << 2) | (s.get('rel_freq', False) << 1) | int(s.get('rel_amp', False)))
    put(49, 52, ds1)
    put(53, 56, (s.get('data_set_2', DATA_SET_2_PRESET) & ~0b10000) | (0b10000 if s.get('mod_display') == 'FM' else 0))
    corr = {v: k for k, v in CORRECTION.items()}[s.get('correction', 'all_on')]
    nibs[62] = (corr << 2) | (0b01 if s.get('fixed_range') else 0)
    total = sum(nibs[i] * 16 + nibs[i + 1] for i in range(0, LEARN_LEN, 2))      # checksum pair (chars 61, 62) is still 00 here
    check = (1 - total) % 256
    nibs[60], nibs[61] = check >> 4, check & 0xF
    return ''.join(chr(65 + n) for n in nibs)


class Fluke6060A(Instrument):
    MODEL = 'Fluke 6060A'
    IDN_MATCH = ('6060A',)
    DEFAULT_ADDRESS = 2                  # the owner's lab address; the manual prints no factory default (rear switches). Change it at construction or in connect().
    DEFAULT_TIMEOUT = 10.0
    COMMANDS = COMMANDS
    RESET_NO_OPC = 'The 6060A has no *OPC? (two-letter commands, Table 2-19): after RC98 the driver reads the learn string back and checks it, instead of waiting.'
    COMMAND_GAP_S = 0.025                # minimum software time per command is 20 ms (Table 2-19, p. 2-62)
    VALID_MIN_S = 0.05                   # the output is valid 45 ms after any hardware change (p. 2-55): the 'srq' method waits this long before it polls
    VALID_TIMEOUT_S = 5.0                # a choice of this driver, not a manual figure
    INTERFACE_MODES = 4                  # @4 = VM1 only (LF terminator, record mode off, unbuffered off, error mode off)
    SETTLE_METHODS = ('vm', 'srq')

    output_off_confirmed = False
    low_rate_fm = False
    options = None
    last_state = None
    last_uncal = None

    def __init__(self, transport, log=None, label=None, address=None, settle='vm'):
        super().__init__(transport, log, label)
        if settle not in self.SETTLE_METHODS:
            raise InstrumentError(f'settle must be one of {self.SETTLE_METHODS}')
        self.settle = settle
        self._address = check_address(address) if address is not None else None
        if self._address is None:
            current = address_of(getattr(transport, 'address', None))
            self._address = current if current is not None else None

    @property
    def address(self) -> int:
        return self._address if self._address is not None else self.DEFAULT_ADDRESS

    def set_address(self, address):
        """Change the GPIB address (before connect)."""
        if self._open:
            raise InstrumentError(f'{self.MODEL}: close the connection before changing the GPIB address')
        self._address = check_address(address)

    # ---- wire access ---------------------------------------------------------------------------------------------------------------------------
    def write(self, cmd, log_as=None):
        time.sleep(self.COMMAND_GAP_S)
        super().write(cmd, log_as)

    def identify(self):
        return self.ask('id').strip()

    def _serial_poll(self) -> int:
        """The status byte by serial poll (SPE / SPD: not a command written to the generator). Needs a transport that can poll."""
        value = serial_poll(self.t)
        self.log.add('--', f'serial poll -> {value}', self.label)
        return value

    # ---- connection ---------------------------------------------------------------------------------------------------------------------------
    def connect(self, address=None):
        """Re-target the transport to the GPIB address (given here, at construction, or DEFAULT_ADDRESS), open, confirm 'ID' answers 6060A, then: device clear, RO0 at once (the
        clear turns RF ON), RC98 preset, CE, the interface modes (VM1 / LF terminator, read back with II), options (IO). Each write once, never retried."""
        if address is not None:
            self.set_address(address)
        retarget(self.t, self.address)
        self.open(verify_model=True)
        try:
            self.t.clear()                                                   # DCL / SDC = CL: RC98, RO1 ... (RF ON at the preset level)
            self.log.add('--', 'device clear sent; RF output is switched off at once', self.label)
            self._rf_off_confirm()
            self.send('reset')
            self._rf_off_confirm()                                            # the preset does not touch RO, but check again before anything else
            self.send('status.clear')
            self._set_modes()
            self.read_options()
            self.check_rejected('connect')
        except Exception:
            self.cleanup()
            self.close()
            raise
        return self

    def _set_modes(self):
        n = self.INTERFACE_MODES if self.settle == 'vm' else 0
        self.send('modes.set', n=n)
        reply = self.query_retry('ii.query').strip()
        got = parse_fields(reply)
        if not got or got[0] != n:
            raise InstrumentError(f'{self.MODEL}: interface modes @{n} were not accepted: II answered {reply!r}')
        if self.settle == 'srq':
            self.send('sm.set', mask=VALID_STB)
            reply = self.query_retry('im.query').strip()
            digits = re.findall(r'\d+', reply)
            if not digits or VALID_STB not in (parse_fields(reply)[0], int(digits[0])):      # the reply base (decimal / octal) is UNVERIFIED: accept either reading
                raise InstrumentError(f'{self.MODEL}: SRQ mask {VALID_STB} was not accepted: IM answered {reply!r}')
        return f'interface modes @{n}' + (f', SRQ mask {VALID_STB}' if self.settle == 'srq' else '')

    def read_options(self) -> dict:
        """IO (read-only, retried once): the installed options. Sets low_rate_fm (-651), which changes the FM range and resolution."""
        reply = self.query_retry('io.query', attempts=2).strip()
        nums = [int(x) for x in re.findall(r'\d+', reply)]
        if len(nums) == 1 and len(reply.strip()) == 3:                      # "352" written as three digits
            nums = [int(c) for c in reply.strip()]
        if len(nums) < 3:
            raise InstrumentError(f'{self.MODEL}: unexpected IO reply {reply!r}')
        self.options = dict(raw=reply, field1=nums[0], field2=nums[1], field3=nums[2], nv_memory=bool(nums[1] & 1), sub_harmonic_ref=bool(nums[1] & 2),
                            high_stability_ref=bool(nums[1] & 4), low_rate_fm=bool(nums[1] & 8), rpp=bool(nums[2] & 1), rear_output=bool(nums[2] & 2))
        self.low_rate_fm = self.options['low_rate_fm']
        return self.options

    def _reset_drain(self, rep, limit=10):
        """IR once (it clears what it reports): an entry found after the reset is a warning."""
        bad, text = self.rejected_entries()
        if bad:
            rep.warnings.append(f'rejected entries after reset: {text}')
            self.log.add('!!', f'rejected entries after reset: {text}', self.label)
            return 'rejected entries drained'
        return 'no rejected entries'

    def _reset_extra(self):
        return [('RF output OFF (RO0, read back with LM99)', self._rf_off_confirm), ('interface modes (read back with II)', self._set_modes),
                ('options (IO)', lambda: f'options {self.read_options()["raw"]!r}')]

    def cleanup(self):
        """Best effort, never raises: RO0, then the generator is handed back to the front panel."""
        try:
            self.send('ro.off')
            self.output_off_confirmed = not self.learn()['rf_on']
        except Exception:
            self.output_off_confirmed = False
        try:
            self.t.go_local()
        except Exception:
            pass

    # ---- settling ------------------------------------------------------------------------------------------------------------------------
    def wait_valid(self):
        """Wait until the RF output is valid. 'vm': VM1 holds the next message until the output is valid, so a read-only ID query is answered when it has settled.
        'srq': wait VALID_MIN_S, then serial poll until bit 16 (output valid) is set, at most VALID_TIMEOUT_S."""
        if self.settle == 'vm':
            if '6060A' not in self.query_retry('id', attempts=2).upper():
                raise InstrumentError(f'{self.MODEL}: no 6060A answer while waiting for a valid output')
            return
        time.sleep(self.VALID_MIN_S)
        end = time.monotonic() + self.VALID_TIMEOUT_S
        while True:
            if self._serial_poll() & VALID_STB:
                return
            if time.monotonic() > end:
                raise InstrumentError(f'{self.MODEL}: the RF output did not become valid within {self.VALID_TIMEOUT_S:g} s')
            time.sleep(0.01)

    # ---- read-back ----------------------------------------------------------------------------------------------------------------------------
    def learn(self, memory=99) -> dict:
        """LM<memory> decoded (read-only: retried up to 3 times). LM99 is the present state."""
        text = self.query_retry('lm.query', attempts=3, values={'mem': memory}).strip()
        state = decode_learn(text)
        if memory == 99:
            self.last_state = state
        return state

    def rejected_entries(self):
        """(bad, text): IR asked ONCE (it clears; never retried). text names every code found."""
        reply = self.ask('ir.query').strip()
        fields = parse_fields(reply)
        if not fields:
            raise InstrumentError(f'{self.MODEL}: unreadable IR reply {reply!r}')
        if not any(fields):
            return False, f'none ({reply})'
        names = describe_fields(fields, REJECT_BITS)
        return True, f'{reply}: ' + '; '.join(names)

    def check_rejected(self, context=''):
        """IR once after a group of writes; raise when the generator rejected one."""
        bad, text = self.rejected_entries()
        if bad:
            raise InstrumentError(f'{self.MODEL} rejected an entry{" (" + context + ")" if context else ""}: {text}')

    def uncal(self):
        """(codes, text): IU once. 'RF output off' (field 3, 400) is not counted as UNCAL."""
        reply = self.ask('iu.query').strip()
        fields = list(parse_fields(reply))
        if len(fields) >= 3:
            fields[2] &= ~RF_OFF_UNCAL
        names = describe_fields(tuple(fields), UNCAL_BITS)
        self.last_uncal = names
        return tuple(fields), (f'{reply}: ' + '; '.join(names)) if names else f'none ({reply})'

    def check_uncal(self, context=''):
        codes, text = self.uncal()
        if any(codes):
            raise InstrumentError(f'{self.MODEL} output is UNCAL{" (" + context + ")" if context else ""}: {text}')

    def compare(self, expect: dict, state: dict | None = None) -> list:
        """Mismatches between a learn state and what was asked (empty list = equal). Keys: frequency_hz (1 Hz), amplitude_dbm (0.05 dB), am_depth_pct (0.5), fm_dev_hz
        (half the FM resolution), mod_rate_hz, step_function, freq_step_hz, amp_step, am_step_pct, fm_step_hz, and any boolean flag (rf_on, int_am, ext_am, int_fm, ext_fm,
        rel_freq, rel_amp, fixed_range), correction, ext_mod_level."""
        state = state or self.learn()
        tol = {'frequency_hz': 1.0, 'amplitude_dbm': 0.05, 'am_depth_pct': 0.5, 'freq_step_hz': 1.0, 'amp_step': 0.05, 'am_step_pct': 0.5,
               'fm_dev_hz': state['fm_res_hz'] / 2 + 1e-6, 'fm_step_hz': state['fm_res_hz'] + 1e-6}
        bad = []
        for key, want in expect.items():
            got = state.get(key)
            if key in tol:
                if got is None or abs(float(got) - float(want)) > tol[key]:
                    bad.append(f'{key}: asked {want:g}, learn string says {got!r}')
            elif got != want:
                bad.append(f'{key}: asked {want!r}, learn string says {got!r}')
        if expect and 'amplitude_dbm' in expect and state['amplitude_units'] != 'dBm':
            bad.append(f'amplitude is displayed in {state["amplitude_units"]}, not dBm')
        return bad

    def verify(self, **expect) -> dict:
        """Read LM99 and raise InstrumentError when it differs from `expect` (see compare)."""
        state = self.learn()
        bad = self.compare(expect, state)
        if bad:
            raise InstrumentError(f'{self.MODEL} read-back refused: ' + '; '.join(bad))
        return state

    # ---- setters: write once, IR, settle, read back, compare ---------------------------------------------------------------------------------------
    def _apply(self, writes, expect, context, uncal=False, allow_uncal=False):
        self.send('status.clear')
        for key, vals in writes:
            self.send(key, **vals)                                            # each write once, never retried
        self.check_rejected(context)
        self.wait_valid()
        state = self.verify(**expect)
        if uncal and not allow_uncal:
            self.check_uncal(context)
        return state

    def set_frequency(self, mhz: float) -> dict:
        """Frequency in MHz (0.1 to 1050, 10 Hz resolution)."""
        if not MIN_MHZ <= mhz <= MAX_MHZ:
            raise InstrumentError(f'{mhz:g} MHz is outside the 6060A range {MIN_MHZ:g} to {MAX_MHZ:g} MHz')
        hz = round(mhz * 1e6 / 10.0) * 10
        return self._apply([('fr.set', {'mhz': hz / 1e6})], {'frequency_hz': hz}, f'{hz / 1e6:.5f} MHz')

    def set_level(self, dbm: float, allow_uncal=False) -> dict:
        """Level in dBm (-137 to +13 calibrated, 0.1 dB). Outside that range only with allow_uncal (to -147.4 / +19), and the UNCAL state is then not an error."""
        lo, hi = (UNCAL_MIN_DBM, UNCAL_MAX_DBM) if allow_uncal else (MIN_DBM, MAX_DBM)
        if not lo <= dbm <= hi:
            raise InstrumentError(f'{dbm:g} dBm is outside {lo:g} to {hi:g} dBm')
        v = round(dbm * 10) / 10.0
        return self._apply([('ap.set', {'dbm': v})], {'amplitude_dbm': v}, f'{v:.1f} dBm', uncal=True, allow_uncal=allow_uncal)

    @staticmethod
    def _on_off(on) -> bool:
        if isinstance(on, str):
            if on.strip().lower() in ('on', '1', 'true'):
                return True
            if on.strip().lower() in ('off', '0', 'false'):
                return False
            raise InstrumentError(f'RF state {on!r} is not on / off')
        return bool(on)

    def rf(self, on) -> dict:
        """RO1 / RO0 ('on' / 'off' or a bool), read back with LM99. Failing to confirm OFF is a SafetyError."""
        want = self._on_off(on)
        self.send('ro.on' if want else 'ro.off')
        self.wait_valid()
        state = self.learn()
        if state['rf_on'] != want:
            if want:
                raise InstrumentError(f'{self.MODEL} did not confirm RF output ON (learn string RF bit {state["rf_on"]})')
            raise SafetyError(f'{self.MODEL} did not confirm RF output OFF (learn string RF bit {state["rf_on"]}); check the front panel')
        return state

    def _rf_off_confirm(self):
        self.rf(False)
        return 'RF output OFF confirmed'

    def end_point(self) -> dict:
        """The end of every test point: RO0, read back with LM99 (SafetyError when it is not off)."""
        return self.rf(False)

    def am(self, depth_pct: float, source: str = 'int', rate_hz: int = 1000, allow_uncal=False, input_applied=True) -> dict:
        """AM on. depth_pct 0 to 99 (above 90 is UNCAL: refused unless allow_uncal); source 'int' (400 or 1000 Hz) or 'ext' (1 V peak at the AM input: the learn string's external-level
        field must read 'valid'; input_applied=False for the 4A-11 step with EXT AM on and NO modulation input, where the field reads 'ext_lo'). The other AM source is switched off."""
        if not 0 <= depth_pct <= MAX_AM_PCT:
            raise InstrumentError(f'AM depth {depth_pct:g} % is outside 0 to {MAX_AM_PCT}')
        pct = round(depth_pct)
        writes, expect = [('am.set', {'pct': pct})], {'am_depth_pct': pct}
        if source == 'int':
            self._rate(rate_hz, writes, expect)
            writes += [('ae.set', {'state': 0}), ('ai.set', {'state': 1})]
            expect.update(int_am=True, ext_am=False)
        elif source == 'ext':
            writes += [('ai.set', {'state': 0}), ('ae.set', {'state': 1})]
            expect.update(int_am=False, ext_am=True)
            if input_applied:
                expect['ext_mod_level'] = 'valid'
        else:
            raise InstrumentError(f"AM source {source!r} is not 'int' or 'ext'")
        return self._apply(writes, expect, f'AM {pct} % {source}', uncal=True, allow_uncal=allow_uncal)

    def fm(self, dev_khz: float, source: str = 'int', rate_hz: int = 1000, allow_uncal=False, input_applied=True) -> dict:
        """FM on. dev_khz 0.1 to 99.9 (0 to 9.99 with the low-rate option -651, found by IO at connect); source 'int' or 'ext'. The other FM source is switched off."""
        top = MAX_FM_KHZ_651 if self.low_rate_fm else MAX_FM_KHZ
        if not 0 <= dev_khz <= top:
            raise InstrumentError(f'FM deviation {dev_khz:g} kHz is outside 0 to {top:g} kHz')
        writes, expect = [('fm.set', {'khz': float(f'{dev_khz:.3g}')})], {'fm_dev_hz': float(f'{dev_khz:.3g}') * 1000.0}
        if source == 'int':
            self._rate(rate_hz, writes, expect)
            writes += [('fe.set', {'state': 0}), ('fi.set', {'state': 1})]
            expect.update(int_fm=True, ext_fm=False)
        elif source == 'ext':
            writes += [('fi.set', {'state': 0}), ('fe.set', {'state': 1})]
            expect.update(int_fm=False, ext_fm=True)
            if input_applied:
                expect['ext_mod_level'] = 'valid'
        else:
            raise InstrumentError(f"FM source {source!r} is not 'int' or 'ext'")
        return self._apply(writes, expect, f'FM {dev_khz:g} kHz {source}', uncal=True, allow_uncal=allow_uncal)

    @staticmethod
    def _rate(rate_hz, writes, expect):
        if rate_hz not in MOD_RATES:
            raise InstrumentError(f'The 6060A internal modulation rate is 400 or 1000 Hz, not {rate_hz!r}')
        writes.insert(0, ('mr.set', {'rate': MOD_RATES[rate_hz]}))
        expect['mod_rate_hz'] = rate_hz

    def mod_off(self) -> dict:
        """Internal and external AM and FM off, read back."""
        writes = [('ai.set', {'state': 0}), ('ae.set', {'state': 0}), ('fi.set', {'state': 0}), ('fe.set', {'state': 0})]
        return self._apply(writes, dict(int_am=False, ext_am=False, int_fm=False, ext_fm=False), 'modulation off')

    # ---- attenuator sections (Section 4A, Fig. 4A-2) ---------------------------------------------------------------------------------------
    def select_section(self, n: int, rf_on: bool = False) -> dict:
        """Attenuator section 0 to 7. Sections 0 to 3 are reached by their level (AP12DB, AP6DB, AP0DB, AP-12DB: the generator picks them itself). Sections 4 to 7 need
        AP-12DB first (valid -17.0 to -11.1 dBm, AM off) and then SP83 / SP84 / SP85 / SP86. SP8x turns RF on and all modulation off; this method puts RF back to
        RO0 afterwards unless rf_on (UNVERIFIED that RO0 / RO1 keep the alternate section). Read back: modulation off, correction on, fixed range off. Any new level entry
        restores the default attenuators."""
        if n in SECTION_LEVEL_DBM:
            return self.set_level(SECTION_LEVEL_DBM[n])
        if n not in ALT_SECTION_CODE:
            raise InstrumentError(f'attenuator section {n!r} is not 0 to 7')
        state = self.learn()
        if state['int_am'] or state['ext_am']:
            raise InstrumentError('AM must be off before an alternate attenuator section is selected (p. 4A-5): call mod_off() first')
        self.set_level(ALT_SECTION_LEVEL_DBM)
        expect = dict(int_am=False, ext_am=False, int_fm=False, ext_fm=False, correction='all_on', fixed_range=False, rel_freq=False, rel_amp=False)
        state = self._apply([('sp.section', {'code': ALT_SECTION_CODE[n]})], dict(expect, rf_on=True), f'section {n} (SP{ALT_SECTION_CODE[n]})')
        if not rf_on:
            state = self.rf(False)
        return state

    def hardware_attenuation(self) -> int:
        """XA (monitor command, read-only): the attenuation in units of 6 dB. Diagnostics; the reply layout is UNVERIFIED."""
        reply = self.query_retry('xa.query').strip()
        nums = re.findall(r'\d+', reply)
        if not nums:
            raise InstrumentError(f'{self.MODEL}: unreadable XA reply {reply!r}')
        return int(nums[0])

    # ---- steps ---------------------------------------------------------------------------------------------------------------------------------
    _STEPS = {   # kind -> (size command, size placeholder, size key, up, down, value key, unit scale)
        'freq': ('fs.set', 'mhz', 'freq_step_hz', 'fu', 'fd', 'frequency_hz', 1e6),
        'level': ('ls.set', 'db', 'amp_step', 'lu', 'ld', 'amplitude_dbm', 1.0),
        'am': ('ps.set', 'pct', 'am_step_pct', 'pu', 'pd', 'am_depth_pct', 1.0),
        'fm': ('ds.set', 'khz', 'fm_step_hz', 'du', 'dd', 'fm_dev_hz', 1000.0),
    }

    def set_step(self, kind: str, size: float) -> dict:
        """Step size of 'freq' (MHz), 'level' (dB), 'am' (%) or 'fm' (kHz). FS / LS / PS / DS only store the size; read back."""
        cmd, ph, key, *_ = self._STEPS[kind]
        scale = self._STEPS[kind][6]
        value = {'freq': round(size * 1e5) / 1e5, 'level': round(size * 10) / 10, 'am': round(size), 'fm': float(f'{size:.3g}')}[kind]
        return self._apply([(cmd, {ph: value})], {key: value * scale}, f'{kind} step {value:g}')

    def step(self, kind: str, count: int) -> dict:
        """count steps up (positive) or down (negative) of 'freq' / 'level' / 'am' / 'fm' (FU/FD, LU/LD, PU/PD, DU/DD), each sent once; the result is read back and must equal
        the value before the steps plus count x the step size (FU / FD also select the frequency step function)."""
        if not count:
            raise InstrumentError('step count must not be zero')
        _cmd, _ph, size_key, up, down, value_key, _scale = self._STEPS[kind]
        before = self.learn()
        want = before[value_key] + count * before[size_key]
        if kind == 'level' and not MIN_DBM <= want <= MAX_DBM:
            raise InstrumentError(f'{want:g} dBm after {count} steps is outside {MIN_DBM:g} to {MAX_DBM:g} dBm')
        if kind == 'freq' and not MIN_MHZ * 1e6 <= want <= MAX_MHZ * 1e6:
            raise InstrumentError(f'{want / 1e6:g} MHz after {count} steps is outside the 6060A range')
        expect = {value_key: want}
        if kind == 'freq':
            expect['step_function'] = 'freq'
        return self._apply([(up if count > 0 else down, {})] * abs(count), expect, f'{count:+d} {kind} steps')

    def step_frequency(self, count: int) -> dict:
        return self.step('freq', count)

    def step_level(self, count: int) -> dict:
        return self.step('level', count)
