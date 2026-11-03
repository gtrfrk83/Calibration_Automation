"""Keithley DMM6500 6 1/2-digit multimeter with scanning (unit under test), SCPI command set, over USB (USBTMC), LAN (VXI-11 / raw socket) or GPIB (option).

STATUS: written from the manual only, NOT yet met on a real instrument.  Every COMMANDS entry is verified=False until the bench session of the
bench-first workflow (NOTES.md 'Bench-first driver workflow') has recorded a real reply and driver_verify has passed.  A command is only
treated as verified when it has all three: a manual page in `ref`, a recorded real reply and a driver_verify pass.

Source: Model DMM6500 Reference Manual DMM6500-901-01 Rev. C (April 2026), section 12 'SCPI command reference' and chapter 15 'Common commands'; every
`ref` below is the printed page number of that manual.  The performance verification limits come from the DMM6500 Calibration and Adjustment Manual
DMM6500-905-01 Rev. E (June 2022), section 2.  NOTHING here uses a calibration / adjustment command: the adjustment of the DMM6500 is TSP only
(Calibration Manual section 3, 'Select the TSP command set') and is not built.

Interface facts used:
  * The DMM6500 has two command sets, SCPI and TSP, chosen from the front panel (MENU > System > Settings > Command Set).  This driver speaks SCPI only
    and checks the *IDN? reply; if the meter is in TSP mode, SCPI commands are rejected (the front-panel setting must be SCPI).  UNVERIFIED: the
    factory default and the exact *IDN? text ('KEITHLEY INSTRUMENTS,MODEL DMM6500,...' expected).
  * :ROUTe:TERMinals? answers FRON or REAR (p. 12-80); the front-panel TERMINALS button is the only way to change it, so the program asks the
    operator and then checks the query.
  * :READ? makes [:SENSe]:COUNt readings and returns the LAST one (p. 12-11); the digitize function uses :READ:DIGitize? and [:SENSe]:DIGitize:COUNt
    (p. 12-13, 12-143) and the readings are fetched with :TRACe:DATA? (p. 12-175).  The manual's 'STATISTICS swipe screen Average' is the mean of
    those readings, computed here.
  * *RST returns the instrument to its defaults and clears the reading buffers (p. 15-7).  Never :SYSTem:POSetup, *SAV, *RCL and no CALibration commands.
Writes are sent once, read back and compared; nothing is retried.  Only read-only queries (:SYST:ERR?, ...) may be retried.
"""
from __future__ import annotations

import math
import re
import statistics

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError
from .transport import TransportError, bus_of

RM = 'Keithley DMM6500 Reference Manual DMM6500-901-01 Rev. C'
CM = 'Keithley DMM6500 Calibration and Adjustment Manual DMM6500-905-01 Rev. E'

# Point kinds -> SCPI function node (the node the per-function commands hang from) and the :FUNCtion argument.
KINDS = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'FREQ', 'CAP', 'TEMP', 'DIGV', 'DIGI')
NODE = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC', 'OHM2': 'RES', 'OHM4': 'FRES', 'FREQ': 'FREQ', 'CAP': 'CAP', 'TEMP': 'TEMP',
        'DIGV': 'DIG:VOLT', 'DIGI': 'DIG:CURR'}
FUNC_NAME = {'DCV': 'VOLT:DC', 'ACV': 'VOLT:AC', 'DCI': 'CURR:DC', 'ACI': 'CURR:AC', 'OHM2': 'RES', 'OHM4': 'FRES', 'FREQ': 'FREQ', 'CAP': 'CAP', 'TEMP': 'TEMP',
             'DIGV': 'VOLT', 'DIGI': 'CURR'}                      # digitize: :SENSe:DIGitize:FUNCtion "VOLTage" | "CURRent" (p. 12-144)
DIGITIZE = ('DIGV', 'DIGI')
HAS_RANGE = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'CAP', 'DIGV', 'DIGI')      # FREQ has a threshold range instead; TEMP has none
HAS_NPLC = ('DCV', 'DCI', 'OHM2', 'OHM4', 'TEMP')                     # integration time in power-line cycles (p. 12-105)
HAS_BAND = ('ACV', 'ACI')                                             # detector bandwidth 3 / 30 / 300 Hz (p. 12-102)
HAS_AZERO = ('DCV', 'DCI', 'OHM2', 'OHM4', 'TEMP')                    # autozero (p. 12-96)
HAS_REL = ('DCV', 'ACV', 'DCI', 'ACI', 'OHM2', 'OHM4', 'FREQ', 'CAP', 'TEMP', 'DIGV', 'DIGI')
FUNC_ACCEPT = {'DCV': ('VOLT:DC', 'VOLT'), 'ACV': ('VOLT:AC',), 'DCI': ('CURR:DC', 'CURR'), 'ACI': ('CURR:AC',), 'OHM2': ('RES',), 'OHM4': ('FRES',),
               'FREQ': ('FREQ',), 'CAP': ('CAP',), 'TEMP': ('TEMP',)}
RANGE_WINDOW = (0.5, 1.25)       # a range query is accepted between 0.5 x and 1.25 x the range asked for (the reply format is UNVERIFIED, see range_ok)
OVERFLOW = 9.0e37                # the DMM6500 reports overflow as +9.9E37 (UNVERIFIED for this model; the 2000 and the Truevolt use the same value)

# printed page of each per-function command family (Reference Manual section 12)
P = dict(func='12-145', dfunc='12-144', count='12-142', dcount='12-143', nplc='12-105', aper='12-82', band='12-102', zimp='12-103', range='12-110', auto='12-109',
         rel='12-115', acq='12-113', azero='12-96', srate='12-124', tcon='12-129', rjsim='12-126', rjsel='12-128', thr='12-131', tran='12-133', unit='12-134',
         four='12-120', three='12-121', ocomp='12-106', odet='12-108', read='12-11', readd='12-13', trace='12-175', clear='12-174', terms='12-80', err='12-158',
         prec='12-44', cls='15-2', esr='15-4', idn='15-5', opc='15-6', rst='15-7', lfr='12-164')


def _p(key, what=''):
    return f'{RM}, p. {P[key]}' + (f' ({what})' if what else '')


def _per_kind():
    """Function-specific commands, one key per function ('<name>.<kind lower case>')."""
    out = {}
    for kind in KINDS:
        k, n = kind.lower(), NODE[kind]
        dig = kind in DIGITIZE
        if dig:
            out[f'func.{k}'] = Cmd(f':SENS:DIG:FUNC "{FUNC_NAME[kind]}"', f'Select digitize {"voltage" if kind == "DIGV" else "current"}',
                                   'Makes the digitize function active (the measure function reads back NONE while a digitize function is active)', kind='set',
                                   readback='dfunc.query', verified=False, ref=_p('dfunc', 'digitize function'))
        else:
            out[f'func.{k}'] = Cmd(f':SENS:FUNC "{FUNC_NAME[kind]}"', f'Select {kind}', f'Makes {kind} the active measure function; read back with :SENS:FUNC?', kind='set',
                                   readback='func.query', verified=False, ref=_p('func', 'measure function'))
        if kind in HAS_RANGE:
            out[f'range.{k}'] = Cmd(f':SENS:{n}:RANG {{range:.9g}}', f'{kind} range', 'Sets the positive full-scale range (an upper limit the instrument rounds up to a range); '
                                    'autorange is then switched off explicitly', placeholders={'range': Placeholder('float', '.9g', 1.0)}, kind='set',
                                    readback=f'range.query.{k}', verified=False, ref=_p('range', 'RANGe[:UPPer] <n>'))
            out[f'range.query.{k}'] = Cmd(f':SENS:{n}:RANG?', f'{kind} range query', 'Reads back the range; the reply format is UNVERIFIED (a number in exponent form expected)',
                                          kind='query', verified=False, ref=_p('range', 'query'))
            out[f'autooff.{k}'] = Cmd(f':SENS:{n}:RANG:AUTO OFF', f'{kind} autorange off', 'Every verification point uses a manual range (no autorange)', kind='set',
                                      readback=f'auto.query.{k}', verified=False, ref=_p('auto', 'RANGe:AUTO <state>'))
            out[f'auto.query.{k}'] = Cmd(f':SENS:{n}:RANG:AUTO?', f'{kind} autorange query', 'Reply format UNVERIFIED (0 / 1 expected)', kind='query', verified=False,
                                         ref=_p('auto', 'query'))
        if kind in HAS_NPLC:
            out[f'nplc.{k}'] = Cmd(f':SENS:{n}:NPLC {{nplc:g}}', f'{kind} integration time (PLC)', 'Power-line cycles; the verification tables are calculated for 1 PLC '
                                   '(Calibration Manual: thermocouple / RTD steps state 1 PLC)', placeholders={'nplc': Placeholder('float', 'g', 1.0)}, kind='set',
                                   readback=f'nplc.query.{k}', verified=False, ref=_p('nplc', 'NPLCycles'))
            out[f'nplc.query.{k}'] = Cmd(f':SENS:{n}:NPLC?', f'{kind} PLC query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('nplc', 'query'))
        if kind in HAS_BAND:
            out[f'band.{k}'] = Cmd(f':SENS:{n}:DET:BAND {{hz:g}}', f'{kind} detector bandwidth', 'Detector bandwidth 3, 30 or 300 Hz. AC is SPECIFIED at 3 Hz (3 Hz to 300 kHz, '
                                   '<= 2 readings/s); the verification tables allow 30 Hz (>= 20 readings/s) or 300 Hz from 1 kHz (Calibration Manual pp. 2-11, 2-37)',
                                   placeholders={'hz': Placeholder('float', 'g', 30.0)}, kind='set', readback=f'band.query.{k}', verified=False,
                                   ref=_p('band', 'DETector:BANDwidth <n>: 3 Hz, 30 Hz or 300 Hz') + f'; {CM} pp. 2-11, 2-37')
            out[f'band.query.{k}'] = Cmd(f':SENS:{n}:DET:BAND?', f'{kind} bandwidth query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('band', 'query'))
        if kind in HAS_AZERO:
            out[f'azero.{k}'] = Cmd(f':SENS:{n}:AZER {{state}}', f'{kind} autozero', 'ON (the default); the specification assumes autozero ON (thermocouple / RTD steps state it)',
                                    placeholders={'state': Placeholder('enum', '', 'ON', enum=('ON', 'OFF'))}, kind='set', readback=f'azero.query.{k}', verified=False,
                                    ref=_p('azero', 'AZERo[:STATe]'))
            out[f'azero.query.{k}'] = Cmd(f':SENS:{n}:AZER?', f'{kind} autozero query', 'Reply format UNVERIFIED (0 / 1 expected)', kind='query', verified=False,
                                          ref=_p('azero', 'query'))
        if kind in HAS_REL:
            out[f'rel.{k}'] = Cmd(f':SENS:{n}:REL:STAT {{state}}', f'{kind} relative offset state', 'Relative offset applied to the readings (the tables use it for the 100 mV '
                                  'range, the 1 nF cable offset and the 10 A zero)', placeholders={'state': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))}, kind='set',
                                  readback=f'rel.query.{k}', verified=False, ref=_p('rel', 'RELative:STATe'))
            out[f'rel.query.{k}'] = Cmd(f':SENS:{n}:REL:STAT?', f'{kind} relative offset query', 'Reply format UNVERIFIED (0 / 1 expected)', kind='query', verified=False,
                                        ref=_p('rel', 'query'))
            out[f'rel.acq.{k}'] = Cmd(f':SENS:{n}:REL:ACQ', f'{kind} acquire relative offset', 'Triggers a new measurement and stores it as the relative offset level', kind='action',
                                      verified=False, ref=_p('acq', 'RELative:ACQuire'))
    # digitize timing: sample rate, aperture (the tables: sample rate 1000, aperture auto or 1 ms, count 100)
    for kind in DIGITIZE:
        k, n = kind.lower(), NODE[kind]
        out[f'srate.{k}'] = Cmd(f':SENS:{n}:SRAT {{srate:g}}', f'{kind} sample rate', 'Digitize sample rate in readings per second (Calibration Manual: 1000)',
                                placeholders={'srate': Placeholder('float', 'g', 1000.0)}, kind='set', readback=f'srate.query.{k}', verified=False, ref=_p('srate', 'SRATe'))
        out[f'srate.query.{k}'] = Cmd(f':SENS:{n}:SRAT?', f'{kind} sample rate query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('srate', 'query'))
        out[f'aper.{k}'] = Cmd(f':SENS:{n}:APER {{aper:g}}', f'{kind} aperture', 'Aperture in seconds (Calibration Manual: Auto or 1 ms). The AUTO setting has no SCPI value '
                               'that the manual states: 1 ms is used', placeholders={'aper': Placeholder('float', 'g', 0.001)}, kind='set', readback=f'aper.query.{k}',
                               verified=False, ref=_p('aper', 'APERture'))
        out[f'aper.query.{k}'] = Cmd(f':SENS:{n}:APER?', f'{kind} aperture query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('aper', 'query'))
    return out


COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the event registers (never overridable)', kind='set', risk='locked', verified=False, ref=f'{RM}, p. {P["cls"]} (*CLS)'),
    'esr.query': Cmd('*ESR?', 'Standard event status', 'Standard event status register (read clears it); registered, not used by the engine', kind='query', verified=False,
                     ref=f'{RM}, p. {P["esr"]} (*ESR?)'),
    'err.query': Cmd(':SYST:ERR?', 'Error queue', 'Oldest error from the event log (reading removes it); the empty-queue reply text is UNVERIFIED (a code 0 / "No error" expected). '
                     'Never overridable', kind='query', risk='locked', verified=False, ref=_p('err', 'SYSTem:ERRor[:NEXT]?')),
    'terminals.query': Cmd(':ROUT:TERM?', 'Input terminals', 'FRON or REAR; the front-panel TERMINALS button is the only way to change it', kind='query', verified=False,
                           ref=_p('terms', 'ROUTe:TERMinals?: FRON or REAR')),
    'lfreq.query': Cmd(':SYST:LFR?', 'Line frequency', '50, 60 or 400 Hz (NPLC conversions); registered, not used by the engine', kind='query', verified=False, ref=_p('lfr', 'SYSTem:LFRequency?')),
    'dfunc.query': Cmd(':SENS:DIG:FUNC?', 'Digitize function query', 'Reply text UNVERIFIED (VOLT / CURR expected; NONE when a measure function is active)', kind='query',
                       verified=False, ref=_p('dfunc', 'query')),
    'func.query': Cmd(':SENS:FUNC?', 'Measure function query', 'Reply text UNVERIFIED (the function name, possibly quoted; NONE when a digitize function is active)', kind='query',
                      verified=False, ref=_p('func', 'query')),
    'form.prec': Cmd(':FORM:ASC:PREC {digits:d}', 'ASCII precision', 'Digits in returned numbers; the default 0 is not described, so 10 is set (the manual\'s example) to keep the full reading',
                     placeholders={'digits': Placeholder('int', 'd', 10)}, kind='set', readback='form.prec.query', verified=False, ref=_p('prec', 'FORMat:ASCii:PRECision')),
    'form.prec.query': Cmd(':FORM:ASC:PREC?', 'ASCII precision query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('prec', 'query')),
    'count': Cmd(':SENS:COUN {count:d}', 'Measure count', 'Number of readings made by :READ? (only the last is returned); 1 for the verification points', placeholders={'count': Placeholder('int', 'd', 1)},
                 kind='set', readback='count.query', verified=False, ref=_p('count', 'COUNt')),
    'count.query': Cmd(':SENS:COUN?', 'Measure count query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('count', 'query')),
    'dig.count': Cmd(':SENS:DIG:COUN {count:d}', 'Digitize count', 'Number of readings digitized (1 to 55,000,000); the tables use 100', placeholders={'count': Placeholder('int', 'd', 100)},
                     kind='set', readback='dig.count.query', verified=False, ref=_p('dcount', 'DIGitize:COUNt')),
    'dig.count.query': Cmd(':SENS:DIG:COUN?', 'Digitize count query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('dcount', 'query')),
    'read': Cmd(':READ?', 'Take a reading', 'Makes the counted readings, stores them in defbuffer1 and returns the last; never retried', kind='query', verified=False, ref=_p('read', ':READ?')),
    'read.dig': Cmd(':READ:DIG?', 'Digitize readings', 'Makes the digitize count of readings and returns the last; the whole set is read with :TRAC:DATA?; never retried', kind='query',
                    verified=False, ref=_p('readd', ':READ:DIGitize?')),
    'trace.clear': Cmd(':TRAC:CLE', 'Clear the reading buffer', 'Clears defbuffer1 before a digitize capture so the first N readings are this capture', kind='set', verified=False,
                       ref=_p('clear', ':TRACe:CLEar')),
    'trace.data': Cmd(':TRAC:DATA? 1,{count:d},"defbuffer1",READ', 'Buffer readings', 'The reading element of the first N entries of defbuffer1 (a read-only query). Which default buffer the '
                      'digitize functions fill is UNVERIFIED (defbuffer1 assumed)', placeholders={'count': Placeholder('int', 'd', 100)}, kind='query', verified=False,
                      ref=_p('trace', ':TRACe:DATA? <start>,<end>,"<buffer>",<elements>')),
    # open-lead detector and offset compensation (4-wire resistance, Calibration Manual p. 2-25: offset compensation ON for 1 ohm to 10 kohm, OFF above; open lead detector OFF)
    'ocomp.fres': Cmd(':SENS:FRES:OCOM {state}', '4-wire offset compensation', 'ON for the 1 ohm to 100 kohm ranges where the Calibration Manual uses it (zero checks, p. 2-25, 2-42), OFF above. The Reference Manual (p. 12-106) says offset-compensated '
                      'ranges stop at 10 kohm, the Calibration Manual warning text says "expected value from 1 to 100000": DISCREPANCY, to be settled on the bench', placeholders={'state': Placeholder('enum', '', 'ON', enum=('ON', 'OFF', 'AUTO'))}, kind='set', readback='ocomp.query.fres',
                      verified=False, ref=_p('ocomp', 'OCOMpensated') + f'; {CM} p. 2-25'),
    'ocomp.query.fres': Cmd(':SENS:FRES:OCOM?', '4-wire offset compensation query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('ocomp', 'query')),
    'odet.fres': Cmd(':SENS:FRES:ODET {state}', '4-wire open-lead detector', 'OFF for the verification (Calibration Manual p. 2-25 step 7)', placeholders={'state': Placeholder('enum', '', 'OFF', enum=('ON', 'OFF'))},
                     kind='set', readback='odet.query.fres', verified=False, ref=_p('odet', 'ODETector') + f'; {CM} p. 2-25'),
    'odet.query.fres': Cmd(':SENS:FRES:ODET?', '4-wire open-lead detector query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('odet', 'query')),
    # DC voltage input impedance (Calibration Manual p. 2-7 step 6: Auto)
    'zimp.dcv': Cmd(':SENS:VOLT:DC:INP {imp}', 'DC volts input impedance', 'AUTO (10 Mohm only on the 100 V and 1000 V ranges, > 10 Gohm on the 100 mV to 10 V ranges); the manual states "Auto" '
                    'on the front panel, the SCPI argument names are UNVERIFIED (AUTO / MOHM10)', placeholders={'imp': Placeholder('enum', '', 'AUTO', enum=('AUTO', 'MOHM10'))},
                    kind='set', readback='zimp.query.dcv', verified=False, ref=_p('zimp', 'INPutimpedance') + f'; {CM} p. 2-7'),
    'zimp.query.dcv': Cmd(':SENS:VOLT:DC:INP?', 'DC volts input impedance query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('zimp', 'query')),
    # frequency (Calibration Manual p. 2-17: aperture 250 ms, threshold range 10 V)
    'aper.freq': Cmd(':SENS:FREQ:APER {aper:g}', 'Frequency gate (aperture)', 'Gate time in seconds: 0.25 (Calibration Manual p. 2-17 step 5)', placeholders={'aper': Placeholder('float', 'g', 0.25)},
                     kind='set', readback='aper.query.freq', verified=False, ref=_p('aper', 'APERture') + f'; {CM} p. 2-17'),
    'aper.query.freq': Cmd(':SENS:FREQ:APER?', 'Frequency gate query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('aper', 'query')),
    'thr.freq': Cmd(':SENS:FREQ:THR:RANG {volts:g}', 'Frequency threshold range', 'Expected input level: 10 V (Calibration Manual p. 2-17 step 6); also turns the threshold autorange off',
                    placeholders={'volts': Placeholder('float', 'g', 10.0)}, kind='set', readback='thr.query.freq', verified=False, ref=_p('thr', 'THReshold:RANGe') + f'; {CM} p. 2-17'),
    'thr.query.freq': Cmd(':SENS:FREQ:THR:RANG?', 'Frequency threshold range query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('thr', 'query')),
    # temperature: thermocouple type J simulated (Calibration Manual p. 2-19/2-20) and PT100 3- / 4-wire (p. 2-23)
    'tran': Cmd(':SENS:TEMP:TRAN {transducer}', 'Temperature transducer', 'TC (thermocouple), FRTD (4-wire RTD) or TRTD (3-wire RTD)', placeholders={'transducer': Placeholder('enum', '', 'TC', enum=('TC', 'FRTD', 'TRTD'))},
                kind='set', readback='tran.query', verified=False, ref=_p('tran', 'TRANsducer: TCouple, THERmistor, RTD, TRTD, FRTD, CJC2001')),
    'tran.query': Cmd(':SENS:TEMP:TRAN?', 'Temperature transducer query', 'Reply text UNVERIFIED (TC / FRTD / TRTD or the long form)', kind='query', verified=False, ref=_p('tran', 'query')),
    'tc.type': Cmd(':SENS:TEMP:TC:TYPE {tctype}', 'Thermocouple type', 'J for the simulated-thermocouple verification', placeholders={'tctype': Placeholder('enum', '', 'J', enum=('B', 'E', 'J', 'K', 'N', 'R', 'S', 'T'))},
                   kind='set', readback='tc.type.query', verified=False, ref=_p('tcon', 'TCouple:TYPE') + f'; {CM} p. 2-20'),
    'tc.type.query': Cmd(':SENS:TEMP:TC:TYPE?', 'Thermocouple type query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('tcon', 'query')),
    'tc.rjsel': Cmd(':SENS:TEMP:TC:RJUN:RSEL SIM', 'Simulated reference junction', 'Front terminals: simulated is the only option', kind='set', readback='tc.rjsel.query', verified=False,
                    ref=_p('rjsel', 'RJUNction:RSELect: SIMulated or EXTernal')),
    'tc.rjsel.query': Cmd(':SENS:TEMP:TC:RJUN:RSEL?', 'Reference junction query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('rjsel', 'query')),
    'tc.rjsim': Cmd(':SENS:TEMP:TC:RJUN:SIM {temp:g}', 'Simulated reference temperature', '0 degC for the verification (Calibration Manual p. 2-20 step 18)', placeholders={'temp': Placeholder('float', 'g', 0.0)},
                    kind='set', readback='tc.rjsim.query', verified=False, ref=_p('rjsim', 'RJUNction:SIMulated') + f'; {CM} p. 2-20'),
    'tc.rjsim.query': Cmd(':SENS:TEMP:TC:RJUN:SIM?', 'Simulated reference temperature query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('rjsim', 'query')),
    'temp.unit': Cmd(':SENS:TEMP:UNIT CELS', 'Temperature unit', 'Degrees Celsius', kind='set', readback='temp.unit.query', verified=False, ref=_p('unit', 'UNIT: KELVin, CELSius, FAHRenheit')),
    'temp.unit.query': Cmd(':SENS:TEMP:UNIT?', 'Temperature unit query', 'Reply format UNVERIFIED (CELS expected)', kind='query', verified=False, ref=_p('unit', 'query')),
    'rtd.four': Cmd(':SENS:TEMP:RTD:FOUR {rtd}', '4-wire RTD type', 'PT100 for the verification (Calibration Manual p. 2-23 step 8)', placeholders={'rtd': Placeholder('enum', '', 'PT100',
                    enum=('PT100', 'PT385', 'PT3916', 'D100', 'F100'))}, kind='set', readback='rtd.four.query', verified=False, ref=_p('four', 'RTD:FOUR') + f'; {CM} p. 2-23'),
    'rtd.four.query': Cmd(':SENS:TEMP:RTD:FOUR?', '4-wire RTD type query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('four', 'query')),
    'rtd.three': Cmd(':SENS:TEMP:RTD:THR {rtd}', '3-wire RTD type', 'PT100 for the verification', placeholders={'rtd': Placeholder('enum', '', 'PT100', enum=('PT100', 'PT385', 'PT3916', 'D100', 'F100'))},
                     kind='set', readback='rtd.three.query', verified=False, ref=_p('three', 'RTD:THRee') + f'; {CM} p. 2-23'),
    'rtd.three.query': Cmd(':SENS:TEMP:RTD:THR?', '3-wire RTD type query', 'Reply format UNVERIFIED', kind='query', verified=False, ref=_p('three', 'query')),
}
COMMANDS.update(_per_kind())
COMMANDS['reset'] = cmdreg.reset_cmd(False, f'{RM}, p. {P["rst"]} (*RST: returns the instrument to default settings and clears the reading buffers; reply behaviour not recorded on a real meter)',
                                     note='Never :SYSTem:POSetup, *SAV or *RCL. The front-panel System Reset the Calibration Manual asks for (p. 2-6) is not the same command: *RST is used and the operator is told.')
COMMANDS['opc.query'] = cmdreg.opc_cmd(False, f'{RM}, p. {P["opc"]} (*OPC?: an ASCII 1 is placed in the output queue when the pending operations are complete); not recorded on a real meter')


def _text(reply):
    return str(reply).strip().strip('"\'').strip().upper()


def _number(reply):
    """The first number in a reply (exponent form, optional units / quotes). InstrumentError when there is none."""
    m = re.search(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?', str(reply))
    if not m:
        raise InstrumentError(f'no number in the reply {str(reply).strip()!r}')
    return float(m.group(0))


def _flag(reply):
    t = _text(reply)
    if t in ('1', '+1', 'ON'):
        return True
    if t in ('0', '+0', 'OFF'):
        return False
    raise InstrumentError(f'expected 0/1 or ON/OFF, the DMM6500 answered {str(reply).strip()!r}')


class KeithleyDMM6500(Instrument):
    MODEL = 'Keithley DMM6500'
    IDN_MATCH = ('DMM6500',)
    COMMANDS = COMMANDS
    DEFAULT_TIMEOUT = 30.0              # an AC reading at the 3 Hz detector bandwidth takes about 2 s; digitize 100 readings at 1000 /s is 0.1 s; DC at 1 PLC far less
    DEFAULT_GPIB_ADDRESS = 16           # UNVERIFIED (the GPIB interface is the optional KTTI-GPIB accessory, Calibration Manual p. 3-3); :SYSTem:GPIB:ADDRess sets it, p. 12-163

    @property
    def bus(self) -> str:
        """'USB', 'LAN', 'GPIB' from the transport (a simulator may carry a .bus attribute)."""
        return getattr(self.t, 'bus', None) or bus_of(str(getattr(self.t, 'name', '') or ''))

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    def connect(self):
        """Open, clear the status registers, confirm the model. There is no remote-enable command to send on USB / LAN / GPIB."""
        self.open(verify_model=False)
        try:
            self.send('status.clear')
            self.idn = self.identify()
        except TransportError as exc:
            self.close()
            raise InstrumentError(f'The DMM6500 did not answer *IDN? ({exc}). Check the cable / VISA address, and that the front-panel command set is SCPI '
                                  '(MENU > System > Settings > Command Set), not TSP.') from exc
        if self.IDN_MATCH and not any(m.upper() in self.idn.upper() for m in self.IDN_MATCH):
            self.close()
            raise InstrumentError(f'Expected a Keithley DMM6500 but the instrument identifies as: {self.idn!r}')
        return self

    def cleanup(self):
        """Nothing is sent: the SCPI command set has no 'return to local' command; the front panel is available at any time."""
        return None

    def _reset_extra(self):
        return [('known measurement state (count 1, ASCII precision)', self._known_state)]

    def _known_state(self):
        """After *RST: measure count 1 and the numeric precision, each set once and read back."""
        self.send('count', count=1)
        if int(round(_number(self.ask('count.query')))) != 1:
            raise InstrumentError('the measure count is not 1 after :SENSe:COUNt 1')
        self.send('form.prec', digits=10)
        if int(round(_number(self.ask('form.prec.query')))) != 10:
            raise InstrumentError('the ASCII precision is not 10 after :FORMat:ASCii:PRECision 10')
        return 'count 1, ASCII precision 10'

    # ---- configuration of one test point (set, read back, compare; a write is never retried) --------------------------------
    @staticmethod
    def range_ok(reply, range_value: float) -> bool:
        """True when the range query reply is the range asked for: 0.5 to 1.25 x the nominal range (so 1010 for the 1000 V range and 757 for the 750 V range pass and a
        neighbouring decade never does). The reply format itself is UNVERIFIED."""
        v = abs(_number(reply))
        return RANGE_WINDOW[0] * range_value <= v <= RANGE_WINDOW[1] * range_value

    def _confirm(self, what, ok, reply):
        if not ok:
            raise InstrumentError(f'{self.label}: {what} was not accepted: the DMM6500 answered {str(reply).strip()!r}')

    def _select(self, kind):
        k = kind.lower()
        self.send(f'func.{k}')
        if kind in DIGITIZE:
            reply = self.ask('dfunc.query')
            self._confirm(f'digitize function {FUNC_NAME[kind]}', _text(reply).startswith(FUNC_NAME[kind][:4]), reply)
        else:
            reply = self.ask('func.query')
            self._confirm(f'function {FUNC_NAME[kind]}', _text(reply).replace('"', '') in FUNC_ACCEPT[kind], reply)

    def _apply_flag(self, key, query, want, what, **vals):
        self.send(key, **vals)
        reply = self.ask(query)
        self._confirm(what, _flag(reply) == want, reply)

    def _apply_number(self, key, query, want, what, rel_tol=1e-6, **vals):
        self.send(key, **vals)
        reply = self.ask(query)
        self._confirm(what, math.isclose(_number(reply), want, rel_tol=rel_tol, abs_tol=1e-12), reply)

    def configure_point(self, point: dict):
        """Function, manual range, speed, filter-free set-up for one verification point. point: kind, range, optional plc (default 1), ac_bandwidth (default 30), srate / count /
        aperture (digitize), ocomp (4-wire), transducer / tc_type / rtd (temperature). Never autorange (the verification tables are per range). DC volts input impedance Auto."""
        kind = point['kind']
        if kind not in KINDS:
            raise InstrumentError(f'{self.label}: no function for kind {kind!r}')
        k = kind.lower()
        self._select(kind)
        if kind in HAS_RANGE:
            rng = float(point['range'])
            self.send(f'range.{k}', range=rng)
            reply = self.ask(f'range.query.{k}')
            self._confirm(f'the {rng:g} range', self.range_ok(reply, rng), reply)
            self._apply_flag(f'autooff.{k}', f'auto.query.{k}', False, 'autorange off')
        if kind in HAS_NPLC:
            self._apply_number(f'nplc.{k}', f'nplc.query.{k}', float(point.get('plc') or 1), 'the PLC setting', nplc=float(point.get('plc') or 1))
        if kind in HAS_AZERO:
            self._apply_flag(f'azero.{k}', f'azero.query.{k}', True, 'autozero on', state='ON')
        if kind in HAS_BAND:
            hz = float(point.get('ac_bandwidth') or 30)
            self._apply_number(f'band.{k}', f'band.query.{k}', hz, f'detector bandwidth {hz:g}', hz=hz)
        if kind == 'DCV':
            self.send('zimp.dcv', imp='AUTO')
            reply = self.ask('zimp.query.dcv')
            self._confirm('input impedance Auto', _text(reply).startswith('AUTO'), reply)
        if kind == 'OHM4':
            ocomp = 'ON' if point.get('ocomp', True) else 'OFF'
            self.send('odet.fres', state='OFF')
            reply = self.ask('odet.query.fres')
            self._confirm('open-lead detector off', not _flag(reply), reply)
            self.send('ocomp.fres', state=ocomp)
            reply = self.ask('ocomp.query.fres')
            self._confirm(f'offset compensation {ocomp}', _text(reply) in ((('ON', '1', '+1') if ocomp == 'ON' else ('OFF', '0', '+0'))), reply)   # reply text UNVERIFIED: ON / 1 or OFF / 0
        if kind in DIGITIZE:
            self._apply_number(f'srate.{k}', f'srate.query.{k}', float(point.get('srate') or 1000), 'the sample rate', srate=float(point.get('srate') or 1000))
            aper = float(point.get('aperture') or 0.001)
            self._apply_number(f'aper.{k}', f'aper.query.{k}', aper, 'the aperture', aper=aper)
            n = int(point.get('count') or 100)
            self._apply_number('dig.count', 'dig.count.query', n, f'digitize count {n}', count=n)
        if kind == 'FREQ':
            self._apply_number('aper.freq', 'aper.query.freq', 0.25, 'the 250 ms gate', aper=0.25)
            self._apply_number('thr.freq', 'thr.query.freq', 10.0, 'the 10 V threshold range', volts=10.0)
        if kind == 'TEMP':
            self.configure_temperature(point)
        if kind in HAS_REL and not point.get('keep_rel'):
            self._apply_flag(f'rel.{k}', f'rel.query.{k}', False, 'relative offset off', state='OFF')

    def configure_temperature(self, point: dict):
        """Transducer (TC / 4-wire / 3-wire RTD), type, simulated reference junction 0 degC, degrees C. Order follows the manual: transducer first, then its type."""
        transducer = point.get('transducer', 'TC')
        self.send('tran', transducer=transducer)
        reply = self.ask('tran.query')
        self._confirm(f'transducer {transducer}', _text(reply).startswith(transducer[:2]), reply)
        if transducer == 'TC':
            self.send('tc.type', tctype=point.get('tc_type', 'J'))
            reply = self.ask('tc.type.query')
            self._confirm(f'thermocouple type {point.get("tc_type", "J")}', _text(reply) == point.get('tc_type', 'J'), reply)
            self.send('tc.rjsel')
            reply = self.ask('tc.rjsel.query')
            self._confirm('simulated reference junction', _text(reply).startswith('SIM'), reply)
            self._apply_number('tc.rjsim', 'tc.rjsim.query', 0.0, 'the 0 degC simulated reference temperature', temp=0.0)
        else:
            key = 'rtd.four' if transducer == 'FRTD' else 'rtd.three'
            self.send(key, rtd=point.get('rtd', 'PT100'))
            reply = self.ask(key + '.query')
            self._confirm(f'RTD type {point.get("rtd", "PT100")}', _text(reply) == point.get('rtd', 'PT100'), reply)
        self.send('temp.unit')
        reply = self.ask('temp.unit.query')
        self._confirm('degrees Celsius', _text(reply).startswith('CEL'), reply)

    def rel_is_on(self, kind='DCV') -> bool:
        """:SENSe:<function>:RELative:STATe? (a read-only query)."""
        return _flag(self.ask(f'rel.query.{kind.lower()}'))

    def acquire_reference(self, kind='DCV') -> float:
        """Relative offset: :REL:ACQ takes a new measurement and stores it as the offset, then REL is enabled and read back. Returns nothing the instrument stated: the
        reference value is not read back (no query for it is documented in the pages used), so the reading afterwards is the offset-corrected one."""
        k = kind.lower()
        self.send(f'rel.acq.{k}')
        self._apply_flag(f'rel.{k}', f'rel.query.{k}', True, 'relative offset on', state='ON')

    # ---- readings ---------------------------------------------------------------------------------------------------------
    @staticmethod
    def _reading(reply) -> float:
        value = _number(reply)
        if not math.isfinite(value) or abs(value) >= OVERFLOW:
            raise InstrumentError(f'The DMM6500 reported an overflow / invalid reading ({str(reply).strip()!r}): wrong range or nothing connected.')
        return value

    def read(self) -> float:
        """:READ? -> one reading. Never retried."""
        return self._reading(self.ask('read'))

    def read_digitize(self) -> dict:
        """Capture [:SENSe]:DIGitize:COUNt readings (buffer cleared first), return {'readings': [...], 'average': mean, 'min', 'max'}. The manual's STATISTICS 'Average' is
        the mean of the captured readings. Never retried (the capture is a write-like action)."""
        n = int(round(_number(self.ask('dig.count.query'))))
        self.send('trace.clear')
        self.ask('read.dig')
        reply = self.ask('trace.data', count=n)
        values = [self._reading(v) for v in str(reply).replace('\n', ',').split(',') if v.strip()]
        if len(values) != n:
            raise InstrumentError(f'{self.label}: expected {n} digitized readings, the DMM6500 returned {len(values)}')
        return {'readings': values, 'average': statistics.fmean(values), 'min': min(values), 'max': max(values)}

    def front_rear(self) -> str:
        """:ROUT:TERM? -> 'FRONT' or 'REAR' (the TERMINALS button cannot be set remotely)."""
        reply = _text(self.ask('terminals.query'))
        return 'FRONT' if reply.startswith('FRON') else 'REAR' if reply.startswith('REAR') else reply

    def check_errors(self, context: str = ''):
        """Raise if the error log holds anything: read until the empty reply (at most 10 entries). The empty-queue reply text is UNVERIFIED: a leading code 0 is treated as empty."""
        found = []
        for _ in range(11):
            reply = self.query_retry('err.query', attempts=3, delay=0.5).strip()
            if self._error_code(reply) == 0 or _text(reply).startswith('NO ERROR'):
                break
            found.append(reply)
        if found:
            raise InstrumentError(f'{self.MODEL} reported an error{" after " + context if context else ""}: ' + ' | '.join(found))
