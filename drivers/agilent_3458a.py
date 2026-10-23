"""Keysight / Agilent (HP) 3458A 8 1/2-digit multimeter over GPIB, driven in HP Multimeter Language (it has NO SCPI).

Source: "Keysight 3458A Multimeter User's Guide" (UG, the printed page numbers equal the PDF page numbers).  Command text and parameters were read from rendered
page images; every Cmd below carries its page.  What the guide does not print (reply layouts, timing, the byte count of a transfer that is not shown, error numbers)
is listed under UNVERIFIED in NOTES.md and the report: nothing is silently assumed.

Language facts used (UG chapter 6, "Command Reference"):
  * GPIB only, factory address 22 (ADDRESS, p. 238).  Query replies are ASCII, numeric under QFORMAT NORM/NUM (power-on NORM, p. 322); ID? answers the text
    "Keysight 3458A" (p. 276; older firmware may say HP3458A: the driver matches on "3458A").
  * RESET (p. 332-333) is the locked reset: the power-on state without cycling power (OFORMAT ASCII, END OFF, NPLC 10, NDIG 7, TRIG AUTO, TARM AUTO, AZERO ON, DCV
    AUTO, INBUF OFF, QFORMAT NORM, math off, error / auxiliary error / status registers cleared).  PRESET NORM (p. 319) is NOT used: it also changes NPLC, NDIG
    and TRIG.  The guide says to send the GPIB device clear (SDC) before RESET from remote (p. 333): reset_to_defaults() does so.
  * END (p. 261): power-on / RESET value OFF (no EOI).  The driver reads ASCII replies up to LF (read termination set at connect) and binary readings by byte count
    (read_raw), so it works with EOI off; it still sets END ALWAYS after the reset as the guide's own programs do for transfers.
  * Readings: the output buffer holds a reading only after a trigger.  TRIG SYN (p. 374-375) makes the controller's read request the trigger, so every read() takes a
    new reading; TRIG SGL + read is the alternative.  TRIG AUTO free-runs (a stale reading may be waiting), so read() refuses it.
  * OFORMAT (p. 308-309): ASCII (15 bytes + CR LF), SREAL (IEEE-754 32 bit), DREAL (IEEE-754 64 bit), no line end for the binary formats; overload is +-1E+38 in
    ASCII, SREAL and DREAL.  Byte order: the guide's SREAL conversion program (p. 153) and DREAL "same as the controller" example (p. 154) are most-significant byte first.
    SINT / DINT need ISCALE? scaling and are not implemented.  Replies to queries are always ASCII.
  * STB? (p. 358) discards pending output and never shows 'ready'; it is used only as the bus-held sequencing barrier of the reset (INBUF OFF holds the bus until a
    command is done, p. 277).  ACAL (p. 234-235) runs with the bus held (INBUF OFF), so the one ACAL write blocks until it ends: the transport timeout is raised for it
    and the write is never retried.
Writes are sent once, read back and compared; nothing is retried.  Only read-only queries (ERRSTR? ...) may be retried.  No CAL / SCAL / SECURE / CALSTR command is in
this driver (calibration writes are out of scope); CALNUM? is a read-only count.
"""
from __future__ import annotations

import math
import re
import struct

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError
from .transport import TransportError

UG = "Keysight 3458A User's Guide"
OVERLOAD_ABS = 9.9e37                     # +-1E+38 is the overload reading in ASCII / SREAL / DREAL (UG p. 309)
DEFAULT_GPIB_ADDRESS = 22                 # UG p. 238
READ_TERMINATION = '\n'                   # ASCII readings and query replies end in CR LF (UG p. 261)

# FUNC numeric query equivalents (UG p. 271-272); only the eight DC / AC / ohms / current functions are implemented
FUNC_NUM = {'DCV': 1, 'ACV': 2, 'ACDCV': 3, 'OHM': 4, 'OHMF': 5, 'DCI': 6, 'ACI': 7, 'ACDCI': 8}
FUNCS = tuple(FUNC_NUM)
DC_FUNCS = ('DCV', 'DCI', 'OHM', 'OHMF')           # autozero applies (UG p. 243): about twice the time per reading
AC_FUNCS = ('ACV', 'ACDCV', 'ACI', 'ACDCI')
CURRENT_FUNCS = ('DCI', 'ACI', 'ACDCI')

# Ranges (nominal, full scale) from the max._input tables, UG p. 273-274 (read from the page images).
# Misprints in the printed tables, read both times: OHM ">12 to 120" row shows a full scale of "120 kOhm" (it is 120 Ohm); the ACI row "0 to .120E-6 -> 100 uA"
# should read .120E-3 or 120E-6 (the next row starts at 120E-6).  The values below are the consistent ones.
_VOLT = ((1e-1, 1.2e-1), (1.0, 1.2), (10.0, 12.0), (100.0, 120.0), (1000.0, 1050.0))
RANGES = {
    'DCV': _VOLT,
    'ACV': ((1e-2, 1.2e-2),) + _VOLT,
    'OHM': tuple((r, r * 1.2) for r in (10.0, 100.0, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9)),
    'DCI': tuple((r, r * 1.2) for r in (1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1)) + ((1.0, 1.05),),
    'ACI': tuple((r, r * 1.2) for r in (1e-4, 1e-3, 1e-2, 1e-1)) + ((1.0, 1.05),),
}
RANGES['ACDCV'] = RANGES['ACV']
RANGES['OHMF'] = RANGES['OHM']
RANGES['ACDCI'] = RANGES['ACI']
TOP_INPUT = {'DCV': 1e3, 'ACV': 1e3, 'ACDCV': 1e3}   # the 1000 V range is selected up to 1E3 (full scale 1050 V); the others up to 1.2 x the range

ENUMS = {
    'trig': {'AUTO': 1, 'EXT': 2, 'SGL': 3, 'HOLD': 4, 'SYN': 5},                      # UG p. 374
    'tarm': {'AUTO': 1, 'EXT': 2, 'SGL': 3, 'HOLD': 4, 'SYN': 5},                      # UG p. 367
    'end': {'OFF': 0, 'ON': 1, 'ALWAYS': 2},                                           # UG p. 261
    'oformat': {'ASCII': 1, 'SINT': 2, 'DINT': 3, 'SREAL': 4, 'DREAL': 5},             # UG p. 308
    'qformat': {'NUM': 0, 'NORM': 1},                                                  # UG p. 322 (ALPHA has no numeric equivalent)
    'onoff': {'OFF': 0, 'ON': 1},
    'azero': {'OFF': 0, 'ON': 1, 'ONCE': 2},                                           # UG p. 243
    'arange': {'OFF': 0, 'ON': 1, 'ONCE': 2},                                          # UG p. 240
    'sample': {'AUTO': 1, 'EXTSYN': 2, 'SYN': 5, 'TIMER': 6, 'LEVEL': 7, 'LINE': 8},   # UG p. 304
    'setacv': {'ANA': 1, 'RNDM': 2, 'SYNC': 3},                                        # UG p. 342
    'coupling': {'DC': 1, 'AC': 2},                                                    # UG p. 281
    'slope': {'NEG': 0, 'POS': 1},                                                     # UG p. 343
    'term': {'OPEN': 0, 'FRONT': 1, 'REAR': 2},                                        # UG p. 371
    'math': {'OFF': 0, 'NULL': 9},                                                     # UG p. 287 (the other operations are not used)
}
_PERSISTENT = {k: v for k, v in ENUMS['trig'].items() if k != 'SGL'}               # events that stay set (SGL reverts to HOLD after one trigger, UG p. 374)
BYTES = {'SREAL': 4, 'DREAL': 8}
ACAL_TYPES = ('ALL', 'DCV', 'AC', 'OHMS')
# ACAL durations and settling times (UG p. 235); the INBUF OFF bus hold lasts for the whole duration
ACAL_SECONDS = {'ALL': 16 * 60, 'DCV': 2 * 60 + 45, 'AC': 2 * 60 + 45, 'OHMS': 11 * 60}
ACAL_SETTLE_SECONDS = {'ALL': 30 * 60, 'DCV': 15 * 60, 'AC': 15 * 60, 'OHMS': 30 * 60}
ACAL_WARMUP_SECONDS = 2 * 3600                       # powered and thermally stable for at least 2 hours before any autocal (UG p. 234)
MAX_ERRORS = 20


def _page(*pages, note=''):
    out = f'{UG}, p. ' + ', '.join(str(p) for p in pages)
    return out + (f' ({note})' if note else '')


def _enum_ph(table, sample=None):
    return Placeholder('enum', '', sample or next(iter(table)), enum=tuple(table))


def _flt(sample, fmt='.9G'):
    return Placeholder('float', fmt, sample)


def _query(template, name, description, pages, note=''):
    return Cmd(template, name, description, kind='query', verified=True, ref=_page(*pages, note=note))


def _set(template, name, description, placeholders, readback, pages, note=''):
    return Cmd(template, name, description, placeholders=placeholders, kind='set', readback=readback, verified=True, ref=_page(*pages, note=note))


COMMANDS = {
    # ---- locked plumbing
    'reset': cmdreg.reset_cmd(True, _page('332-333', note='RESET: power-on state without cycling power; PRESET NORM (p. 319) is not used'), template='RESET',
                              note='RESET clears the error, auxiliary error and status registers and reading memory; it sets END OFF, OFORMAT ASCII, NPLC 10, NDIG 7, TRIG AUTO.'),
    'status.clear': Cmd('CSB', 'Clear status byte', 'Clears the status register (never overridable)', kind='set', risk='locked', verified=True, ref=_page(249)),
    'opc.query': Cmd('STB?', 'Status byte (sequencing barrier)', 'The bus is held until the previous command is done (INBUF OFF, p. 277), so the answer arrives when the reset is finished. '
                     'The reply is NOT an operation-complete flag: bit 4 (ready) is always clear and STB? discards pending output (never overridable)',
                     kind='query', risk='locked', verified=True, ref=_page(358, 277, note='used only as a barrier; "ready" would need a serial poll, which the transport does not have')),
    'err.query': Cmd('ERRSTR?', 'Error string', 'Least significant set bit of the error or auxiliary error register, then cleared: "<number>,<message>"; 0,"NO ERROR" when empty '
                     '(never overridable)', kind='query', risk='locked', verified=True, ref=_page(264)),
    'id.query': Cmd('ID?', 'Identity', 'Answers "Keysight 3458A" (p. 276); match on "3458A" (never overridable)', kind='query', risk='locked', verified=True, ref=_page(276)),
    # ---- read-only queries
    'err.register': _query('ERR?', 'Error register', 'Weighted sum of the set error bits (reading clears the register)', (262, 263)),
    'err.aux': _query('AUXERR?', 'Auxiliary error register', 'Weighted sum of the set hardware-error bits (reading clears the register)', (241, 242)),
    'rev.query': _query('REV?', 'Firmware revision', 'Master and slave processor revision, two numbers separated by a comma', (334,)),
    'temp.query': _query('TEMP?', 'Internal temperature', 'Degrees Celsius; used to decide when an autocal is advisable', (370,)),
    'line.query': _query('LINE?', 'Line frequency', 'Measures and returns the AC line frequency', (285,)),
    'calnum.query': _query('CALNUM?', 'Calibration number', 'How many times the meter has been calibrated (read-only)', (246,)),
    'opt.query': _query('OPT?', 'Options', '0 = no options, 1 = extended reading memory', (314,)),
    'term.query': _query('TERM?', 'Front / Rear terminals', 'Which input terminals the front panel Terminals switch selects (1 = FRONT, 2 = REAR); cannot be set remotely', (371,)),
    'inbuf.query': _query('INBUF?', 'Input buffer', '0 = bus held while a command runs (the RESET state), 1 = commands buffered', (277,)),
    # ---- function, range, integration
    'func.set': _set('FUNC {function},{max_input:.9G}', 'Function and fixed range', 'Selects the function and the range holding max_input (an absolute value; never AUTO)',
                     {'function': _enum_ph(FUNC_NUM, 'DCV'), 'max_input': _flt(10.0)}, 'func.query', (271, 273, 274),
                     note='FUNC [function][,max._input][,%_resolution]; the range tables are on p. 273-274'),
    'func.query': _query('FUNC?', 'Function query', 'Two responses: the function (numeric equivalent) and the present range', (275,), note='reply layout of the range number is UNVERIFIED'),
    'range.set': _set('RANGE {max_input:.9G}', 'Range', 'Fixed range holding max_input', {'max_input': _flt(10.0)}, 'range.query', (324, 325, 326)),
    'range.query': _query('RANGE?', 'Range query', 'The present measurement range', (327,)),
    'arange.set': _set('ARANGE {mode}', 'Autorange', 'OFF / ON / ONCE', {'mode': _enum_ph(ENUMS['arange'], 'OFF')}, 'arange.query', (240,)),
    'arange.query': _query('ARANGE?', 'Autorange query', '0 = off, 1 = on, 2 = once', (240, 241)),
    'nplc.set': _set('NPLC {nplc:.9G}', 'Integration time (PLC)', 'Power line cycles of the A/D converter; 1 PLC steps to 10, 10 PLC steps to 1000 (p. 301-302)',
                     {'nplc': _flt(10.0)}, 'nplc.query', (301, 302, 303)),
    'nplc.query': _query('NPLC?', 'PLC query', 'The integration time in PLCs (may differ from the NPLC last sent, p. 303)', (303,)),
    'aper.set': _set('APER {seconds:.9G}', 'Integration time (aperture)', 'A/D integration time in seconds, 0 to 1 s in 100 ns steps', {'seconds': _flt(1e-3)}, 'aper.query', (239,)),
    'aper.query': _query('APER?', 'Aperture query', 'The integration time in seconds', (239,)),
    'ndig.set': _set('NDIG {digits:d}', 'Display digits', '3 to 8 (the display digits only, not the converter resolution)',
                     {'digits': Placeholder('int', 'd', 8)}, 'ndig.query', (300, 301)),
    'ndig.query': _query('NDIG?', 'Digits query', 'The displayed number of digits', (301,)),
    'azero.set': _set('AZERO {mode}', 'Autozero', 'OFF / ON / ONCE (DC volts, DC current and ohms)', {'mode': _enum_ph(ENUMS['azero'], 'ON')}, 'azero.query', (243,)),
    'azero.query': _query('AZERO?', 'Autozero query', '0 = off, 1 = on, 2 = once', (243,)),
    'fixedz.set': _set('FIXEDZ {mode}', 'Fixed input resistance (DC volts)', 'OFF / ON (10 Mohm on every DCV range)', {'mode': _enum_ph(ENUMS['onoff'], 'OFF')}, 'fixedz.query', (267,)),
    'fixedz.query': _query('FIXEDZ?', 'FIXEDZ query', '0 = off, 1 = on', (267,)),
    'lfreq.set': _set('LFREQ {hz:.9G}', 'A/D reference (line) frequency', '45 to 65 Hz or 360 to 440 Hz (divided by 8)', {'hz': _flt(50.0)}, 'lfreq.query', (284, 285)),
    'lfreq.line': Cmd('LFREQ LINE', 'Reference frequency from the line', 'Measures the line frequency and sets the reference frequency to it', kind='action', verified=True, ref=_page(284)),
    'lfreq.query': _query('LFREQ?', 'Reference frequency query', 'The reference frequency (period step 100 ns)', (285,)),
    'delay.set': _set('DELAY {seconds:.9G}', 'Trigger-to-sample delay', 'Seconds, 100 ns to 6000 s; -1 = automatic (the RESET value)', {'seconds': _flt(0.0)}, 'delay.query', (253, 254)),
    'delay.query': _query('DELAY?', 'Delay query', 'The delay in seconds', (254,)),
    'setacv.set': _set('SETACV {method}', 'AC RMS method', 'ANA (analog) / RNDM / SYNC', {'method': _enum_ph(ENUMS['setacv'], 'ANA')}, 'setacv.query', (342,)),
    'setacv.query': _query('SETACV?', 'AC method query', '1 = ANA, 2 = RNDM, 3 = SYNC', (342,)),
    'acband.set': _set('ACBAND {low:.9G},{high:.9G}', 'AC bandwidth', 'Lowest and highest expected frequency component (Hz)', {'low': _flt(20.0), 'high': _flt(2e6)}, 'acband.query', (236, 237)),
    'acband.query': _query('ACBAND?', 'AC bandwidth query', 'Two numbers: the low and the high frequency', (237,)),
    'level.set': _set('LEVEL {percent:.9G},{coupling}', 'Trigger level', 'Level trigger percentage of the range and coupling (AC / DC)',
                      {'percent': _flt(0.0), 'coupling': _enum_ph(ENUMS['coupling'], 'AC')}, 'level.query', (281, 282)),
    'level.query': _query('LEVEL?', 'Level query', 'Two responses: the percentage and the coupling', (282,)),
    'slope.set': _set('SLOPE {slope}', 'Trigger slope', 'POS / NEG', {'slope': _enum_ph(ENUMS['slope'], 'POS')}, 'slope.query', (343,)),
    'slope.query': _query('SLOPE?', 'Slope query', '0 = NEG, 1 = POS', (343,)),
    # ---- trigger and transfer
    'trig.set': _set('TRIG {event}', 'Trigger event', 'AUTO / EXT / HOLD / SYN (SYN: the controller read request is the trigger).  SGL is the separate action trig.sgl: it fires once '
                     'and the event reverts to HOLD, so it can never be read back as SGL', {'event': _enum_ph(_PERSISTENT, 'SYN')}, 'trig.query', (374, 375)),
    'trig.sgl': Cmd('TRIG SGL', 'Single trigger', 'One trigger, then the trigger event reverts to HOLD (an action: the reading is then read from the bus)', kind='action', verified=True, ref=_page(374)),
    'trig.query': _query('TRIG?', 'Trigger query', '1 AUTO, 2 EXT, 3 SGL, 4 HOLD, 5 SYN', (375,)),
    'tarm.set': _set('TARM {event}', 'Trigger arm event', 'AUTO / EXT / HOLD / SYN (SGL arms once and then becomes HOLD, so it is not offered)', {'event': _enum_ph(_PERSISTENT, 'AUTO')},
                     'tarm.query', (366, 367)),
    'tarm.query': _query('TARM?', 'Trigger arm query', '1 AUTO, 2 EXT, 3 SGL, 4 HOLD, 5 SYN', (367,)),
    'nrdgs.set': _set('NRDGS {count:d},{event}', 'Readings per trigger', 'Count (1 to 16777215) and the sample event',
                      {'count': Placeholder('int', 'd', 1), 'event': _enum_ph(ENUMS['sample'], 'AUTO')}, 'nrdgs.query', (304, 305)),
    'nrdgs.query': _query('NRDGS?', 'Readings query', 'Two responses: the count and the sample event', (305,)),
    'end.set': _set('END {mode}', 'GPIB EOI', 'OFF / ON / ALWAYS (power-on and RESET: OFF)', {'mode': _enum_ph(ENUMS['end'], 'ALWAYS')}, 'end.query', (261, 262)),
    'end.query': _query('END?', 'EOI query', '0 OFF, 1 ON, 2 ALWAYS', (262,)),
    'oformat.set': _set('OFORMAT {fmt}', 'Reading output format', 'ASCII / SREAL / DREAL (SINT and DINT need ISCALE? and are not used)', {'fmt': _enum_ph({'ASCII': 1, 'SREAL': 4, 'DREAL': 5}, 'ASCII')},
                        'oformat.query', (308, 309)),
    'oformat.query': _query('OFORMAT?', 'Output format query', '1 ASCII, 2 SINT, 3 DINT, 4 SREAL, 5 DREAL', (308,)),
    'qformat.set': _set('QFORMAT {type}', 'Query format', 'NUM / NORM: numeric query replies without headers (ALPHA is never used)', {'type': _enum_ph(ENUMS['qformat'], 'NORM')}, 'qformat.query', (322, 323)),
    'qformat.query': _query('QFORMAT?', 'Query format query', '0 NUM, 1 NORM', (323,)),
    # ---- null / offset
    'math.set': _set('MATH {operation}', 'Real-time math', 'OFF or NULL (reading minus the OFFSET register; the register is loaded with the first reading)',
                     {'operation': _enum_ph(ENUMS['math'], 'OFF')}, 'math.query', (287, 288, 289)),
    'math.query': _query('MATH?', 'Math query', 'Two responses: the enabled operations (numeric equivalents; NULL = 9)', (289,)),
    'smath.offset': _set('SMATH OFFSET,{value:.9G}', 'Write the OFFSET register', 'The subtrahend of NULL', {'value': _flt(0.0)}, 'rmath.offset', (344, 345)),
    'rmath.offset': Cmd('RMATH OFFSET', 'Read the OFFSET register', 'The reply is always ASCII', kind='query', verified=True, ref=_page(334, 335)),
    # ---- autocal (the only calibration-related command in the driver: it adjusts nothing against a standard)
    'acal': Cmd('ACAL {type}', 'Autocal', 'Self-calibration ALL / DCV / AC / OHMS for an UNsecured autocal; takes minutes (ALL 16 min) with the bus held (never overridable)',
                placeholders={'type': _enum_ph(dict.fromkeys(ACAL_TYPES), 'ALL')}, kind='action', risk='locked', verified=True, ref=_page(234, 235)),
    'acal.secured': Cmd('ACAL {type},{code}', 'Autocal (secured)', 'Autocal with the security code; the code is never logged (never overridable)',
                        placeholders={'type': _enum_ph(dict.fromkeys(ACAL_TYPES), 'ALL'), 'code': Placeholder('secret', '', 'X')}, kind='action', risk='locked', verified=True,
                        ref=_page(234, 235)),
}


# ---- reply parsing ------------------------------------------------------------------------------------------------------------------------------
def _text(reply) -> str:
    return str(reply).strip().strip('"\'').strip().upper()


def _number(reply) -> float:
    m = re.search(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', str(reply))
    if not m:
        raise InstrumentError(f'no number in the reply {str(reply).strip()!r}')
    return float(m.group(0))


def _parts(reply) -> list:
    return [p.strip() for p in str(reply).strip().split(',')]


class OverloadError(InstrumentError):
    """The reading is the overload value (+-1E+38): the signal does not fit the range, or nothing is connected where a signal is expected."""


def select_range(function: str, max_input: float):
    """(nominal range, full scale) the max._input parameter selects for a function (UG p. 273-274).  Raises InstrumentError for a value no range holds."""
    if function not in RANGES:
        raise InstrumentError(f'3458A: no range table for function {function!r}')
    x = float(max_input)                                   # -1 means AUTO to the meter (UG p. 273): a negative number is refused, never taken as its absolute value
    if not math.isfinite(x) or x <= 0:
        raise InstrumentError(f'3458A: max_input must be a positive number (autorange is never used), got {max_input!r}')
    top = TOP_INPUT.get(function)
    last = RANGES[function][-1][0]
    for nominal, full in RANGES[function]:
        if x <= (top if (nominal == last and top is not None) else round(1.2 * nominal, 12)):
            return nominal, full
    raise InstrumentError(f'3458A: {x:g} is above the highest {function} range (max_input up to {top if top is not None else round(1.2 * RANGES[function][-1][0], 12):g})')


def nplc_ok(nplc: float) -> bool:
    """True when nplc is on the instrument's grid (UG p. 301-302): 0 to 1 in fine steps, 1 to 10 in 1 PLC steps, 10 to 1000 in 10 PLC steps."""
    if not math.isfinite(nplc) or nplc < 0 or nplc > 1000:
        return False
    if nplc <= 1:
        return True
    if nplc <= 10:
        return math.isclose(nplc, round(nplc), abs_tol=1e-9)
    return math.isclose(nplc / 10, round(nplc / 10), abs_tol=1e-9)


def decode_reading(data, fmt: str = 'ASCII') -> float:
    """One reading from an ASCII reply (str) or a binary transfer (bytes of SREAL / DREAL, most significant byte first).  The value is not range-checked."""
    if fmt == 'ASCII':
        text = data.decode('ascii', 'replace') if isinstance(data, (bytes, bytearray)) else str(data)
        text = text.strip()
        if not text or ',' in text:
            raise InstrumentError(f'3458A: expected one ASCII reading, got {text!r}')
        try:
            return float(text)
        except ValueError as exc:
            raise InstrumentError(f'3458A: not a number: {text!r}') from exc
    if fmt not in BYTES:
        raise InstrumentError(f'3458A: no decoder for the output format {fmt!r}')
    raw = bytes(data)
    if len(raw) != BYTES[fmt]:
        raise InstrumentError(f'3458A: {fmt} needs {BYTES[fmt]} bytes, got {len(raw)}')
    return struct.unpack('>f' if fmt == 'SREAL' else '>d', raw)[0]


def encode_reading(value: float, fmt: str = 'SREAL') -> bytes:
    """The bytes the meter would send for a value (test and simulator helper)."""
    if fmt not in BYTES:
        raise InstrumentError(f'3458A: no encoder for the output format {fmt!r}')
    return struct.pack('>f' if fmt == 'SREAL' else '>d', value)


def check_overload(value: float) -> float:
    """A finite reading, or OverloadError for +-1E+38 (UG p. 309).  SREAL rounds slightly below 1E+38, hence the 9.9E+37 threshold."""
    if not math.isfinite(value) or abs(value) >= OVERLOAD_ABS:
        raise OverloadError(f'The 3458A reported an overload ({value:g}): the signal does not fit the range, or nothing is connected.')
    return value


# How each registered set is confirmed: (read-back key, [(placeholder, comparison), ...]) - one comparison per comma-separated field of the reply.
# A comparison is a dict (enum name -> numeric equivalent), 'float', 'plc', 'aper', 'int' or 'range'.
CONFIRM = {
    'func.set': ('func.query', [('function', FUNC_NUM), ('max_input', 'range')]),
    'range.set': ('range.query', [('max_input', 'range')]),
    'arange.set': ('arange.query', [('mode', ENUMS['arange'])]),
    'nplc.set': ('nplc.query', [('nplc', 'plc')]),
    'aper.set': ('aper.query', [('seconds', 'aper')]),
    'ndig.set': ('ndig.query', [('digits', 'int')]),
    'azero.set': ('azero.query', [('mode', ENUMS['azero'])]),
    'fixedz.set': ('fixedz.query', [('mode', ENUMS['onoff'])]),
    'lfreq.set': ('lfreq.query', [('hz', 'lfreq')]),
    'delay.set': ('delay.query', [('seconds', 'float')]),
    'setacv.set': ('setacv.query', [('method', ENUMS['setacv'])]),
    'acband.set': ('acband.query', [('low', 'float'), ('high', 'float')]),
    'level.set': ('level.query', [('percent', 'float'), ('coupling', ENUMS['coupling'])]),
    'slope.set': ('slope.query', [('slope', ENUMS['slope'])]),
    'trig.set': ('trig.query', [('event', ENUMS['trig'])]),
    'tarm.set': ('tarm.query', [('event', ENUMS['tarm'])]),
    'nrdgs.set': ('nrdgs.query', [('count', 'int'), ('event', ENUMS['sample'])]),
    'end.set': ('end.query', [('mode', ENUMS['end'])]),
    'oformat.set': ('oformat.query', [('fmt', ENUMS['oformat'])]),
    'qformat.set': ('qformat.query', [('type', ENUMS['qformat'])]),
    'math.set': ('math.query', [('operation', ENUMS['math'])]),
    'smath.offset': ('rmath.offset', [('value', 'float')]),
}
_FLOAT_TOL = {'float': dict(rel_tol=1e-6, abs_tol=1e-12), 'plc': dict(rel_tol=2e-5, abs_tol=2e-5), 'aper': dict(rel_tol=1e-6, abs_tol=2e-7),
              'lfreq': dict(rel_tol=1e-4, abs_tol=1e-6)}        # LFREQ? returns the value the 100 ns period step gives (UG p. 285)


class Agilent3458A(Instrument):
    MODEL = 'Keysight 3458A'
    SHORT = '3458A'
    IDN_MATCH = ('3458A',)
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 30.0              # a reading at the default 10 PLC with autozero takes about 0.4 s: this is the floor, reading_timeout() scales it up
    DEFAULT_GPIB_ADDRESS = DEFAULT_GPIB_ADDRESS
    RESET_OPC_TIMEOUT = 30.0

    def __init__(self, transport, log=None, label=None):
        super().__init__(transport, log, label)
        self._power_on_state()

    def _power_on_state(self):
        """What the driver believes the meter is set to; RESET (and power on) give these values (UG p. 332-333)."""
        self.function = 'DCV'
        self.nplc = 10.0
        self.aperture = None
        self.trigger = 'AUTO'
        self.out_format = 'ASCII'
        self.autozero = True
        self.nrdgs = 1

    # ---- lifecycle -------------------------------------------------------------------------------------------------------------------------
    def identify(self):
        return self.ask('id.query').strip()

    def connect(self):
        """Open, set the LF read termination, device clear, clear the status byte, confirm the model with ID?, then learn the output format and trigger event
        with read-only queries.  Nothing is reset here: reset_to_defaults() does that."""
        self.open(verify_model=False)
        self.t.set_read_termination(READ_TERMINATION)
        self.t.clear()
        self.send('status.clear')
        try:
            self.idn = self.identify()
        except TransportError as exc:
            self.close()
            raise InstrumentError(f'The {self.SHORT} did not answer ID? ({exc}). Check the GPIB address (factory 22) and the interface.') from exc
        if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Expected a {self.SHORT} but the instrument identifies as: {self.idn!r}')
        self._sync_state()
        return self

    def _sync_state(self):
        fmt = self._enum_name('oformat', self.query_retry('oformat.query', attempts=3, delay=0.5))
        if fmt not in ('ASCII', 'SREAL', 'DREAL'):
            raise InstrumentError(f'{self.label}: the output format is {fmt}; only ASCII, SREAL and DREAL are supported. Run the reset first.')
        self.out_format = fmt
        self.trigger = self._enum_name('trig', self.query_retry('trig.query', attempts=3, delay=0.5))

    @staticmethod
    def _enum_name(table, reply) -> str:
        """The parameter name for a numeric (or alpha) query reply: tolerant of a leading field list, quotes and exponent forms."""
        mapping = ENUMS[table]
        first = _parts(reply)[0]
        if _text(first) in mapping:
            return _text(first)
        try:
            num = int(round(_number(first)))
        except InstrumentError:
            return _text(first)
        for name, value in mapping.items():
            if value == num:
                return name
        return f'#{num}'

    def local(self):
        """Back to the front panel: GTL over GPIB (the transport sends it)."""
        self.t.go_local()

    def cleanup(self):
        try:
            self.local()
        except Exception:
            pass

    # ---- reset (UG p. 332-333) ---------------------------------------------------------------------------------------------------------------
    def reset_to_defaults(self):
        """GPIB device clear first (UG p. 333: the meter may be busy or the bus held), then the base sequence: RESET, CSB, STB? barrier, drain ERRSTR?, extras."""
        try:
            self.t.clear()
        except Exception:                                   # the clear is advisory; the RESET result is what matters
            pass
        rep = super().reset_to_defaults()
        self._power_on_state()
        return rep

    def _reset_extra(self):
        return [('EOI after every reading (END ALWAYS)', lambda: self._set_end_after_reset()),
                ('known state (OFORMAT ASCII, numeric queries, bus held, autozero on)', self._known_state)]

    def _set_end_after_reset(self):
        self.set_confirmed('end.set', mode='ALWAYS')
        return 'END ALWAYS'

    def _known_state(self):
        problems = []
        if self._enum_name('oformat', self.ask('oformat.query')) != 'ASCII':
            problems.append('output format is not ASCII')
        if self._enum_name('qformat', self.ask('qformat.query')) not in ('NUM', 'NORM'):
            problems.append('query format is not numeric')
        if int(round(_number(self.ask('inbuf.query')))) != 0:
            problems.append('the input buffer is ON (the bus is not held while a command runs)')
        if int(round(_number(self.ask('azero.query')))) != 1:
            problems.append('autozero is not ON')
        if problems:
            raise InstrumentError('; '.join(problems))
        return 'ASCII, numeric queries, INBUF OFF, autozero on'

    # ---- confirmed writes (set, read back, compare; never retried) -------------------------------------------------------------------------------
    @staticmethod
    def _field_ok(how, field, value, function=None) -> bool:
        if isinstance(how, dict):
            if _text(field) == str(value).upper():
                return True
            try:
                return int(round(_number(field))) == how[value]
            except (InstrumentError, KeyError):
                return False
        number = _number(field)
        if how == 'int':
            return int(round(number)) == int(value)
        if how == 'range':
            nominal, full = select_range(function, value)
            return math.isclose(abs(number), nominal, rel_tol=1e-3) or math.isclose(abs(number), full, rel_tol=1e-3)
        return math.isclose(number, float(value), **_FLOAT_TOL[how])

    def set_confirmed(self, key: str, **values) -> str:
        """Send one registered set command ONCE, read the paired query back and compare every field.  Returns the read-back reply.
        Raises InstrumentError when the meter's answer differs; the write is never repeated."""
        if key not in CONFIRM:
            raise InstrumentError(f'{self.label}: {key!r} has no read-back comparison')
        query_key, fields = CONFIRM[key]
        self.send(key, **values)
        reply = self.ask(query_key)
        parts = _parts(reply)
        for index, (name, how) in enumerate(fields):
            if index >= len(parts) or not self._field_ok(how, parts[index], values[name], function=values.get('function') or self.function):
                raise InstrumentError(f'{self.label}: {key} {name}={values[name]!r} was not accepted: {query_key} answered {str(reply).strip()!r}')
        return str(reply).strip()

    # ---- configuration of one test point -------------------------------------------------------------------------------------------------------
    def reading_timeout(self) -> float:
        """Transport timeout (seconds) for one reading: scales with the integration time (worst case a 50 Hz reference: 20 ms per PLC), doubled for the autozero of the
        DC functions, plus a settling allowance for the AC functions.  This is a heuristic (UNVERIFIED): the guide gives the formula for the integration time, not for
        the total reading time."""
        plc = self.nplc if self.aperture is None else self.aperture * 50.0
        seconds = plc * 0.02 * (2 if (self.function in DC_FUNCS and self.autozero) else 1)
        if self.function in AC_FUNCS:
            seconds += 15.0
        return max(self.DEFAULT_TIMEOUT, 5.0 + 2.0 * seconds)

    @staticmethod
    def acal_timeout(kind: str) -> float:
        """Transport timeout for the ACAL write: the guide's duration (p. 235) with 25 % and a minute extra."""
        return ACAL_SECONDS[kind] * 1.25 + 60.0

    def configure(self, function, range, nplc=10, aperture=None, ndig=None, trigger='SYN', autozero=None):
        """One measurement setup: function and a fixed range (FUNC, never autorange), integration time (NPLC, or APER when `aperture` is given), displayed digits,
        trigger event (default SYN: each read takes a new reading).  Every write is sent once and read back; autorange must read back off.  Ends with an
        error-queue check.  `range` is the largest expected absolute input (UG p. 273-274: 0.1 A selects the 100 mA range, 1 selects the 1 A range ...)."""
        if function not in FUNC_NUM:
            raise InstrumentError(f'{self.label}: function {function!r} is not supported (use one of {", ".join(FUNCS)})')
        select_range(function, range)                               # refuses 0, negative, AUTO and a value above the top range before anything is sent
        if trigger not in ENUMS['trig']:
            raise InstrumentError(f'{self.label}: trigger {trigger!r} is not one of {", ".join(ENUMS["trig"])}')
        if aperture is None and not nplc_ok(float(nplc)):
            raise InstrumentError(f'{self.label}: {nplc} PLC is not on the meter\'s grid (0 to 1, 1 PLC steps to 10, 10 PLC steps to 1000)')
        if aperture is not None and not 0 <= float(aperture) <= 1:
            raise InstrumentError(f'{self.label}: aperture {aperture} s is outside 0 to 1 s')
        self.set_confirmed('func.set', function=function, max_input=float(range))
        self.function = function
        if int(round(_number(self.ask('arange.query')))) != 0:
            raise InstrumentError(f'{self.label}: autorange is still on after FUNC {function},{float(range):g}: a fixed range was not accepted')
        if aperture is not None:
            self.set_confirmed('aper.set', seconds=float(aperture))
            self.aperture = float(aperture)
        else:
            self.set_confirmed('nplc.set', nplc=float(nplc))
            self.nplc, self.aperture = float(nplc), None
        if autozero is not None:
            self.set_confirmed('azero.set', mode='ON' if autozero else 'OFF')
            self.autozero = bool(autozero)
        if ndig is not None:
            if not 3 <= int(ndig) <= 8:
                raise InstrumentError(f'{self.label}: NDIG {ndig} is outside 3 to 8')
            self.set_confirmed('ndig.set', digits=int(ndig))
        self.set_trigger(trigger)
        self.t.set_timeout(self.reading_timeout())
        self.check_errors(f'configure {function} {float(range):g}')

    def set_trigger(self, event: str):
        """TRIG <event>, read back.  'SGL' is the driver's single-trigger mode: the meter is put in HOLD (read back) and every read() sends TRIG SGL itself."""
        if event not in ENUMS['trig']:
            raise InstrumentError(f'{self.label}: trigger {event!r} is not one of {", ".join(ENUMS["trig"])}')
        self.set_confirmed('trig.set', event='HOLD' if event == 'SGL' else event)
        self.trigger = event

    def set_output_format(self, fmt: str):
        """OFORMAT ASCII / SREAL / DREAL, read back.  Sets what read() expects on the bus."""
        if fmt not in BYTES and fmt != 'ASCII':
            raise InstrumentError(f'{self.label}: output format {fmt!r} is not supported (ASCII, SREAL, DREAL)')
        self.set_confirmed('oformat.set', fmt=fmt)
        self.out_format = fmt

    # ---- readings --------------------------------------------------------------------------------------------------------------------------------
    def _receive(self):
        """One reading from the bus in the current output format.  No command is sent: with TRIG SYN the read request is the trigger."""
        fmt = self.out_format
        try:
            if fmt == 'ASCII':
                reply = self.t.read()
                self.log.add('<<', reply.strip(), self.label)
                return decode_reading(reply, 'ASCII')
            data = self.t.read_raw(BYTES[fmt])
        except TransportError as exc:
            raise InstrumentError(f'{self.label}: no reading arrived (trigger {self.trigger}, {self.out_format}): {exc}') from exc
        self.log.add('<<', f'<{fmt} {len(data)} bytes {bytes(data).hex()}>', self.label)
        return decode_reading(data, fmt)

    def read(self) -> float:
        """One reading.  TRIG SYN: the read request triggers it; TRIG SGL: a single trigger is sent first.  Any other trigger event is refused (AUTO free-runs and may
        hand over a stale reading; HOLD / EXT give no reading).  Never retried; an overload raises OverloadError."""
        if self.trigger == 'SGL':
            self.send('trig.sgl')                                    # one trigger; the meter then reverts to HOLD (UG p. 374), so each read sends its own
            return check_overload(self._receive())
        if self.trigger != 'SYN':
            raise InstrumentError(f'{self.label}: read() needs TRIG SYN or SGL, the trigger event is {self.trigger}; call configure() or set_trigger()')
        return check_overload(self._receive())

    def read_n(self, count: int) -> list:
        """`count` consecutive readings (each its own trigger).  Stops at the first failure."""
        if int(count) < 1:
            raise InstrumentError(f'{self.label}: count must be at least 1')
        return [self.read() for _ in range(int(count))]

    # ---- null / offset (MATH NULL, UG p. 287-289 and 344-345) ----------------------------------------------------------------------------------------
    def null(self, offset=None) -> float:
        """Enable NULL and load the OFFSET register with a reading taken now (the input must be in the state to be nulled: short or open, as the procedure says), the
        way the guide's own example does (p. 290).  With `offset`, that value is then written to the register (SMATH OFFSET) and read back.  Returns the register."""
        self.set_confirmed('math.set', operation='NULL')
        self._receive_for_null()                                     # the reading that is loaded into the OFFSET register (its nulled result is 0)
        if offset is not None:
            self.set_confirmed('smath.offset', value=float(offset))
        value = self.offset()
        self.check_errors('null')
        return value

    def _receive_for_null(self):
        if self.trigger == 'SGL':
            self.send('trig.sgl')
        elif self.trigger != 'SYN':
            raise InstrumentError(f'{self.label}: NULL needs TRIG SYN or SGL, the trigger event is {self.trigger}')
        return self._receive()

    def null_off(self):
        """MATH OFF, read back."""
        self.set_confirmed('math.set', operation='OFF')

    def offset(self) -> float:
        """The OFFSET register (RMATH OFFSET; always an ASCII reply)."""
        return _number(self.query_retry('rmath.offset', attempts=3, delay=0.5))

    # ---- queries ---------------------------------------------------------------------------------------------------------------------------------
    def temperature(self) -> float:
        """TEMP? -> degrees Celsius (a guide for when an autocal is advisable, UG p. 370 and 234)."""
        return _number(self.query_retry('temp.query', attempts=3, delay=0.5))

    def revision(self) -> tuple:
        """REV? -> (master, slave) firmware revision numbers as text."""
        parts = _parts(self.query_retry('rev.query', attempts=3, delay=0.5))
        return (parts[0], parts[1] if len(parts) > 1 else '')

    def terminals(self) -> str:
        """TERM? -> 'FRONT' or 'REAR' (the Terminals switch; it cannot be set remotely).  The current inputs (I) exist on both panels; the switch decides which."""
        return self._enum_name('term', self.query_retry('term.query', attempts=3, delay=0.5))

    def check_errors(self, context: str = ''):
        """Raise if the error registers hold anything: ERRSTR? until it answers 0,"NO ERROR" (at most 20 reads: 15 error bits and 15 auxiliary bits)."""
        found = []
        for _ in range(MAX_ERRORS + 10):
            reply = self.query_retry('err.query', attempts=3, delay=0.5).strip()
            if self._error_code(reply) == 0:
                break
            found.append(reply)
        if found:
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: ' + ' | '.join(found))

    def state_summary(self) -> dict:
        """Read-only snapshot of the settings a procedure depends on: {name: reply text}.  It sends queries only (never ERRSTR? / ERR?, which would clear errors, and never
        STB?, which discards output).  A query that fails is reported as 'ERROR: ...' instead of raising."""
        keys = (('id', 'id.query'), ('revision', 'rev.query'), ('function,range', 'func.query'), ('autorange', 'arange.query'), ('nplc', 'nplc.query'), ('aperture', 'aper.query'),
                ('ndig', 'ndig.query'), ('trigger', 'trig.query'), ('trigger arm', 'tarm.query'), ('readings', 'nrdgs.query'), ('end', 'end.query'),
                ('output format', 'oformat.query'), ('query format', 'qformat.query'), ('autozero', 'azero.query'), ('fixed input z', 'fixedz.query'),
                ('math', 'math.query'), ('reference frequency', 'lfreq.query'), ('delay', 'delay.query'), ('input buffer', 'inbuf.query'), ('terminals', 'term.query'),
                ('temperature', 'temp.query'), ('calibration number', 'calnum.query'))
        out = {}
        for name, key in keys:
            try:
                out[name] = self.query_retry(key, attempts=2, delay=0.2).strip()
            except Exception as exc:                                  # noqa: BLE001 - a summary reports, it does not stop
                out[name] = f'ERROR: {exc}'
        return out

    # ---- autocal (UG p. 234-235) ---------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def acal_info(kind: str = 'ALL') -> dict:
        """Durations from the guide: seconds the ACAL runs, seconds to let the meter settle afterwards, and the 2 hour warm-up."""
        if kind not in ACAL_TYPES:
            raise InstrumentError(f'3458A: ACAL type {kind!r} is not one of {", ".join(ACAL_TYPES)}')
        return dict(type=kind, run_seconds=ACAL_SECONDS[kind], settle_seconds=ACAL_SETTLE_SECONDS[kind], warmup_seconds=ACAL_WARMUP_SECONDS)

    def acal(self, kind: str = 'ALL', code: str | None = None, inputs_disconnected: bool = False) -> dict:
        """Run an autocal.  The operator must have disconnected every input signal (p. 235) and the meter must have been on for 2 hours: the caller confirms the first with
        inputs_disconnected=True (SafetyError otherwise).  INBUF must be OFF (read-only check) so the bus is held and the one write blocks until the autocal ends, with the
        transport timeout raised for it.  The write is never retried; a timeout leaves the state unknown and raises InstrumentError.  `code` is the security code of a
        secured autocal; it goes on the wire but never into the log.  Returns the durations and the temperature afterwards."""
        info = self.acal_info(kind)
        if not inputs_disconnected:
            raise SafetyError(f'{self.label}: disconnect every input signal and confirm (inputs_disconnected=True) before an autocal (UG p. 235)')
        if int(round(_number(self.ask('inbuf.query')))) != 0:
            raise InstrumentError(f'{self.label}: INBUF is ON: the bus is not held during the autocal, so it cannot be waited for. Run the reset first.')
        self.check_errors('before ACAL')
        before = getattr(self.t, 'timeout', None)
        self.t.set_timeout(self.acal_timeout(kind))
        try:
            try:
                if code is None:
                    self.send('acal', type=kind)
                else:
                    self.send('acal.secured', type=kind, code=code)
            except TransportError as exc:
                raise InstrumentError(f'{self.label}: ACAL {kind} did not complete within {self.acal_timeout(kind):.0f} s ({exc}). Its state is unknown; it was NOT repeated.') from exc
        finally:
            self.t.set_timeout(before if before is not None else self.reading_timeout())
        self.check_errors(f'ACAL {kind}')
        info['temperature_c'] = self.temperature()
        return info
