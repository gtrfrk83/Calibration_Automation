"""Tektronix TBS1000 (non-C: TBS1022 / 1042 / 1062 / 1064 / 1102 / 1104 / 1152 / 1154) digital storage oscilloscope over USB (USBTMC / VISA).

The TBS1000 is covered by the SAME programmer manual as the TDS2000C: "TBS1000B/EDU, TBS1000, TDS2000C/TDS1000C-EDU, TDS2000B/TDS1000B,
TDS2000/TDS1000, TDS200 and TPS2000B/TPS2000 Series Digital Oscilloscopes Programmer" (077-0444-03 Rev B), whose title page and every page footer
name the TBS1000.  So this driver IS drivers/tektronix_tds2000c.py: every command, read-back, tolerance and wait is inherited unchanged (the same wire
text); only the identification differs (the *IDN? text says TBS, the model list and the four-channel models are the TBS1000's).

COMMAND_PAGES below lists every command the inherited driver sends, with the 077-0444-03 page where it was checked for the TBS1000 (printed page
numbers 2-nn; the PDF page is the printed page + 18).  Findings are recorded per command (TBS1000 applicability, syntax).  The inherited driver still
sends through raw write / query (legacy, locked by tests/golden/tektronix_tds2000c.json); the registry entries below (reset, *CLS, *OPC?) are the
TBS1000's own, with verified=True and the page, and do not change the TDS2000C driver's flags.
"""
from __future__ import annotations

import re

import cmdreg
from .tektronix_tds2000c import TektronixTDS2000C

_REF = 'TBS1000/TDS2000 family Programmer manual 077-0444-03 Rev B'
MODEL_RE = re.compile(r'TBS\s*(1(?:02|04|06|10|15)[24])(?![0-9A-Z])', re.I)     # TBS1022 ... TBS1154; never TBS1102B / TBS1102C
FOUR_CHANNEL = ('1064', '1104', '1154')

# Every command the inherited TektronixTDS2000C methods send: (wire header, printed page, applies to the TBS1000 per the page, note)
COMMAND_PAGES = {
    '*CLS': ('2-58', True, ''),
    'HEADer OFF': ('2-108 / 2-109', True, 'HEADer { <NR1> | OFF | ON }'),
    'VERBose OFF': ('2-207', True, ''),
    '*IDN?': ('2-116 / 2-117', True, 'TBS1000 reply format "TEKTRONIX/<model number>,<serial number>, CF:91.1CT FV:v..." (p. 2-117)'),
    '*OPC?': ('2-152', True, ''),
    '*ESR?': ('2-84 / 2-85', True, ''),
    'EVMsg?': ('2-85 / 2-86', True, ''),
    'FACtory': ('2-86 / 2-87', True, 'turns HEADer ON (re-sent OFF afterwards); does not change the verbose state or calibration data'),
    'DIAg:RESUlt:FLAg?': ('2-78', True, 'PASS / FAIL'),
    'DIAg:RESUlt:LOG?': ('2-79', True, ''),
    '*CAL?': ('2-48 / 2-49', True, '0 = completed without errors'),
    'CALibrate:STATUS?': ('2-51', True, 'PASS / FAIL'),
    'SELect:CH<x> ON|OFF': ('2-172', True, ''),
    'CH<x>:COUPling DC': ('2-53', True, 'CH1..CH4 on four-channel models'),
    'CH<x>:BANdwidth ON|OFF': ('2-52', True, 'below 5 mV/div the full bandwidth is 20 MHz on the TBS1000 (p. 2-52)'),
    'CH<x>:PRObe 1': ('2-56', True, ''),
    'CH<x>:SCAle': ('2-56 / 2-57', True, ''),
    'CH<x>:POSition': ('2-55', True, 'divisions'),
    'ACQuire:MODe SAMple|AVErage': ('2-40', True, ''),
    'ACQuire:NUMAVg 16': ('2-41 / 2-42', True, '4, 16, 64 or 128'),
    'ACQuire:STOPAfter RUNSTop': ('2-43', True, ''),
    'ACQuire:STATE RUN': ('2-42', True, 'resets the acquisition count'),
    'ACQuire:NUMACq?': ('2-41', True, ''),
    'HORizontal:MAIn:SCAle': ('2-112', True, '1-2.5-5 sequence'),
    'HORizontal:MAIn:POSition': ('2-112', True, 'seconds, trigger point to centre graticule'),
    'TRIGger:MAIn:TYPe EDGE': ('2-201 / 2-202', True, ''),
    'TRIGger:MAIn:EDGE:SOUrce CH<x>|EXT': ('2-196', True, ''),
    'TRIGger:MAIn:EDGE:SLOpe RISe|FALL': ('2-195', True, ''),
    'TRIGger:MAIn:EDGE:COUPling DC|NOISErej': ('2-195', True, ''),
    'TRIGger:MAIn:MODe AUTO|NORMal': ('2-198', True, ''),
    'TRIGger:MAIn SETLevel': ('2-194', True, 'ignored with event 221 when the acquisition is stopped'),
    'TRIGger:STATE?': ('2-205 / 2-206', True, 'ARMED, READY, TRIGGER, AUTO, SAVE, SCAN'),
    'MEASUrement:IMMed:SOUrce CH<x>': ('2-138', True, 'MEASUrement:IMMed:SOUrce[1]'),
    'MEASUrement:IMMed:TYPe MEAN|PK2pk': ('2-139', True, 'non-TBS1000B syntax list'),
    'MEASUrement:IMMed:VALue?': ('2-143', True, ''),
    'DATa:SOUrce CH<x>': ('2-72', True, ''),
    'DATa:ENCdg ASCIi': ('2-70 / 2-71', True, ''),
    'DATa:WIDth 1': ('2-74', True, ''),
    'DATa:STARt / DATa:STOP': ('2-72 / 2-73', True, '1 to 2500'),
    'WFMPre:XINcr?': ('2-216 / 2-217', True, ''),
    'WFMPre:XZEro?': ('2-218 / 2-219', True, 'position of the first sample relative to the trigger'),
    'WFMPre:YMUlt?': ('2-219', True, 'value = (curve - YOFf) * YMUlt + YZEro'),
    'WFMPre:YOFf?': ('2-220', True, ''),
    'WFMPre:YZEro?': ('2-222', True, ''),
    'CURVe?': ('2-68', True, ''),
}

COMMANDS = {
    'status.clear': cmdreg.Cmd('*CLS', 'Clear status', 'Clears the status registers (never overridable)', kind='set', risk='locked', verified=True,
                               ref=_REF + ', *CLS p. 2-58'),
}
COMMANDS['reset'] = cmdreg.reset_cmd(True, _REF + ', FACtory pp. 2-86 / 2-87 (applies to the TBS1000)', template='FACtory',
                                     note='FACtory (Default Setup), not *RST; the self calibration is never part of the reset')
COMMANDS['opc.query'] = cmdreg.opc_cmd(True, _REF + ', *OPC? p. 2-152')


class TektronixTBS1000(TektronixTDS2000C):
    MODEL = 'Tektronix TBS1000'
    COMMANDS = COMMANDS
    IDN_MATCH = ('TBS',)

    def connect(self):
        """The TDS2000C connect (*CLS, HEADer OFF, VERBose OFF, *IDN?), then the TBS1000 model and channel count from the *IDN? text."""
        super().connect()
        self.model = self.model_from_idn(self.idn)
        self.channels = 4 if self.model in FOUR_CHANNEL else 2
        return self

    @staticmethod
    def model_from_idn(idn: str) -> str:
        """'1104' from 'TEKTRONIX,TBS 1104,C012345,CF:91.1CT FV:v4.00'; '' for another model (a TBS1000B or TBS1000C is not this procedure)."""
        m = MODEL_RE.search(idn or '')
        return m.group(1) if m else ''
