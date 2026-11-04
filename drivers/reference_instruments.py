"""Stimulus and reference instruments used with the MDO4000C procedure.

Fluke96270A      RF reference source (RF section: phase noise, amplitude, IMD, crosstalk, TPA functional check)
AgilentAFG       Agilent/Keysight 33220A (20 MHz) and 33250A (80 MHz) function / arbitrary generators
ReferenceMeter   any SCPI DMM or frequency counter (AFG frequency / amplitude / offset checks)

Every setter reads the value back and compares it; none of them is retried. RF and generator outputs are switched OFF at cleanup.
The 96270A command names are in RF_COMMANDS. They were checked against the 96000 Series Remote Programmers Manual (April 2014 Rev. 2):
INSTrument (p38), OUTPut (p39), POWer (p41), FREQuency (p42), UNIT (p53), SYSTem:ERRor (p55), *IDN? (p57), coupled commands (p60-62).
"""
from __future__ import annotations

import math
import re
import time

import cmdreg
from cmdreg import Cmd, Placeholder
from .base import Instrument, InstrumentError, SafetyError

_RF = '96000 Series Remote Programmers Manual (April 2014 Rev. 2)'


def _rf(topic, page):
    return f'{_RF}: {topic} (p. {page})'


# Fluke 96270A. The command names were checked against the manual, not run on hardware, so verified=False throughout. OUTP ON / OUTP OFF /
# OUTP? change or confirm the RF output (risk 'output'); *CLS and SYST:ERR? are bootstrap / error-queue plumbing (risk 'locked').
# Neither kind can be overridden.
RF_COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
    'inst.set': Cmd('INST SINE', 'Select the leveled-sine instrument', 'SINE is the leveled-sine logical instrument; selecting it also puts the output into standby',
                    kind='set', readback='inst.query', verified=False, ref=_rf('INSTrument', 38)),
    'inst.query': Cmd('INST?', 'Selected instrument', kind='query', verified=False, ref=_rf('INSTrument?', 38)),
    'unit.set': Cmd('UNIT:POW DBM', 'Power units dBm', 'Level commands are in the units set here, not always dBm', kind='set',
                    readback='unit.query', verified=False, ref=_rf('UNIT', 53)),
    'unit.query': Cmd('UNIT:POW?', 'Power units', kind='query', verified=False, ref=_rf('UNIT', 53)),
    'poffs.set': Cmd('POW:OFFS:STAT 0', 'Power offset off', 'A front-panel offset would shift the real output', kind='set',
                     readback='poffs.query', verified=False, ref=_rf('POWer', 41)),
    'poffs.query': Cmd('POW:OFFS:STAT?', 'Power offset state', kind='query', verified=False, ref=_rf('POWer', 41)),
    'foffs.set': Cmd('FREQ:OFFS:STAT 0', 'Frequency offset off', 'Same for frequency', kind='set', readback='foffs.query', verified=False,
                     ref=_rf('FREQuency', 42)),
    'foffs.query': Cmd('FREQ:OFFS:STAT?', 'Frequency offset state', kind='query', verified=False, ref=_rf('FREQuency', 42)),
    'freq.level': Cmd('FREQ {f:.12g};:POW {p:.3f}', 'Frequency and level', 'One message so the source applies its frequency / power coupling',
                      placeholders={'f': Placeholder('float', '.12g', 1e6), 'p': Placeholder('float', '.3f', 0.0)}, kind='set',
                      readback='freq.query', verified=False, ref=_rf('FREQuency / POWer, coupled commands', '42, 60-62')),
    'freq.query': Cmd('FREQ?', 'Frequency', kind='query', verified=False, ref=_rf('FREQuency', 42)),
    'level.query': Cmd('POW?', 'Level', kind='query', verified=False, ref=_rf('POWer', 41)),
    'outp.on': Cmd('OUTP ON', 'RF output on', 'Enables the RF output (never overridable)', kind='set', readback='outp.query', risk='output',
                   verified=False, ref=_rf('OUTPut', 39)),
    'outp.off': Cmd('OUTP OFF', 'RF output off', 'Disables the RF output (never overridable)', kind='set', readback='outp.query',
                    risk='output', verified=False, ref=_rf('OUTPut', 39)),
    'outp.query': Cmd('OUTP?', 'RF output state', 'Confirms on / off (never overridable)', kind='query', risk='output', verified=False,
                      ref=_rf('OUTPut', 39)),
    'err.query': Cmd('SYST:ERR?', 'Error queue', "'0' when the queue is empty (never overridable)", kind='query', risk='locked',
                     verified=False, ref=_rf('SYSTem:ERRor', 55)),
}

# Agilent 33220A / 33250A as the generator under test in the MDO4000C procedure. Generator commands are unverified (NOTES.md). This driver
# uses APPLy, which switches the output ON on the real generator (33220A User's Guide p. 188), so the two APPLy commands are risk 'output'
# (never overridable) even though the procedure sends OUTPut OFF first; OUTPut ON / OFF are 'output' as well.
AFG_COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
    'outp.on': Cmd('OUTPut ON', 'Output on', 'Enables the output (never overridable)', kind='set', risk='output', verified=False),
    'outp.off': Cmd('OUTPut OFF', 'Output off', 'Disables the output (never overridable)', kind='set', risk='output', verified=False),
    'load.50': Cmd('OUTPut:LOAD 50', 'Output termination 50 ohm', kind='set', verified=False),
    'load.inf': Cmd('OUTPut:LOAD INF', 'Output termination High Z', kind='set', verified=False),
    'apply.sin': Cmd('APPLy:SINusoid {frequency_hz:.9g},{vpp:.9g},0', 'Apply sine', 'Frequency, Vpp, 0 V offset. APPLy switches the output on (never overridable)',
                     placeholders={'frequency_hz': Placeholder('float', '.9g', 1000.0), 'vpp': Placeholder('float', '.9g', 1.0)}, kind='set',
                     risk='output', verified=False),
    'apply.squ': Cmd('APPLy:SQUare {frequency_hz:.9g},{vpp:.9g},0', 'Apply square', 'Frequency, Vpp, 0 V offset. APPLy switches the output on (never overridable)',
                     placeholders={'frequency_hz': Placeholder('float', '.9g', 1000.0), 'vpp': Placeholder('float', '.9g', 1.0)}, kind='set',
                     risk='output', verified=False),
    'freq.query': Cmd('FREQuency?', 'Frequency', kind='query', verified=False),
    'volt.query': Cmd('VOLTage?', 'Amplitude', kind='query', verified=False),
    'err.query': Cmd('SYSTem:ERRor?', 'Error queue', "Oldest error; '+0' when empty (never overridable)", kind='query', risk='locked', verified=False),
}

# Generic SCPI DMM / counter / power meter (no manuals supplied): all unverified.
METER_COMMANDS = {
    'status.clear': Cmd('*CLS', 'Clear status', 'Clears the status registers and the error queue (never overridable)', kind='set',
                        risk='locked', verified=False),
    'freq.meas': Cmd('MEASure:FREQuency?', 'Measure frequency', kind='query', verified=False),
    'power.meas': Cmd('MEASure:POWer?', 'Measure power (dBm)', 'Power-meter reading; unverified (no manual supplied)', kind='query', verified=False),
    'conf.vac': Cmd('CONFigure:VOLTage:AC', 'Configure AC volts', kind='set', verified=False),
    'vac.band': Cmd('VOLTage:AC:BANDwidth 200', 'AC bandwidth 200 Hz', kind='set', verified=False),
    'conf.vdc': Cmd('CONFigure:VOLTage:DC', 'Configure DC volts', kind='set', verified=False),
    'read': Cmd('READ?', 'Read', kind='query', verified=False),
}

RF_COMMANDS['reset'] = cmdreg.reset_cmd(True, "96270A Operator Manual p. 3-46 (Master Reset is equivalent to the GPIB command *RST); the Remote Programmers Manual page for *RST was not checked",
                                        note='The connect-time known state (SINE, dBm, offsets off, output OFF) is applied again afterwards')
RF_COMMANDS['opc.query'] = cmdreg.opc_cmd(False, '96000 Series Remote Programmers Manual: *OPC? not checked')
AFG_COMMANDS['reset'] = cmdreg.reset_cmd(False, "33220A / 33250A User's Guide: *RST not checked (manuals not available to the session that wrote this)",
                                         note='Output is confirmed OFF afterwards (OUTPut OFF, OUTPut?)')
AFG_COMMANDS['opc.query'] = cmdreg.opc_cmd(False, "33220A / 33250A User's Guide: *OPC? not checked")
AFG_COMMANDS['outp.query'] = Cmd('OUTPut?', 'Output state', 'Confirms on / off after the reset (never overridable)', kind='query', risk='output', verified=False)
METER_COMMANDS['reset'] = cmdreg.reset_cmd(False, 'generic SCPI meter: no manual supplied, *RST is the IEEE 488.2 common command (unverified for the actual model)')
METER_COMMANDS['opc.query'] = cmdreg.opc_cmd(False, 'generic SCPI meter: no manual supplied')


# ---- Fluke 96270A power-meter mode (PMETer logical instrument): ADDED subset, no existing command above is changed ---------------------------------------------------------
# Confirmed on the RENDERED pages of the 96000 Series Remote Programmers Manual (Rev. 1, 10/14): INSTrument p. 32, PMETer subsystem p. 41, Trigger subsystem p. 42, UNIT p. 47.
# verified=True here means "the command text and its parameters were read on that page"; nothing has been run on hardware. NOT verified (and flagged in the report):
#   * ROHDE & SCHWARZ NRP40T SENSOR SUPPORT IS UNVERIFIED: the manual never mentions NRP or Rohde & Schwarz. :PMET:IDN? is only asked to see that SOME sensor is fitted (the manual says it
#     returns NONE, NONE, NONE, NONE when none is); whether the 96270A accepts an NRP40T, which frequency / average ranges it allows and what it reports are not in this manual,
#   * whether :PMET:READ? follows UNIT:POW (the manual says UNIT:POW sets "the units of all power commands of the currently selected instrument", not that readings follow it): read_dbm()
#     therefore refuses a reading that is not plausible in dBm instead of assuming it,
#   * the time :PMET:ZERO? / :PMET:READ? take (the manual gives none): the reads use the transport timeout.
PMETER_COMMANDS = {
    'pm.inst.set': Cmd('INST PMET', 'Select the power-meter instrument', 'PMETer is a logical instrument of the 96270A; selecting it puts the output into standby and makes the other logical instruments '
                       'unavailable until one is selected again', kind='set', readback='inst.query', verified=True, ref=_rf('INSTrument[:SELect] PMETer', 32)),
    'pm.unit.set': Cmd('UNIT:POW {unit}', 'Power units (power meter)', 'DBM or W for the power commands of the SELECTED instrument (select PMETer first)',
                       placeholders={'unit': Placeholder('enum', '', 'DBM', enum=('DBM', 'W'))}, kind='set', readback='unit.query', verified=True, ref=_rf('UNIT:POWer', 47)),
    'pm.freq.set': Cmd('PMET1:FREQ {hz:.12g}', 'Power meter frequency', 'Frequency at which the sensor measures power (power-on 1E6 Hz). Sensor limits are UNVERIFIED (NRP40T not in the manual)',
                       placeholders={'hz': Placeholder('float', '.12g', 1e9)}, kind='set', readback='pm.freq.query', verified=True, ref=_rf(':PMETer:FREQuency', 41)),
    'pm.freq.query': Cmd('PMET1:FREQ?', 'Power meter frequency', kind='query', verified=True, ref=_rf(':PMETer:FREQuency?', 41)),
    'pm.aver.set': Cmd('PMET1:AVER {n}', 'Power meter averaging', 'Readings averaged: AUTO or 1, 2, 4, 8 ... 32768',
                       placeholders={'n': Placeholder('enum', '', 'AUTO', enum=('AUTO', '1', '2', '4', '8', '16', '32', '64', '128', '256', '512', '1024', '2048', '4096', '8192', '16384', '32768'))},
                       kind='set', readback='pm.aver.query', verified=True, ref=_rf(':PMETer:AVERage', 41)),
    'pm.aver.query': Cmd('PMET1:AVER?', 'Power meter averaging', kind='query', verified=True, ref=_rf(':PMETer:AVERage?', 41)),
    'pm.trig.set': Cmd('PMET1:TRIG {mode}', 'Power meter trigger mode', 'SINGle: :READ? triggers one reading and returns it. CONTinuous: free running (power-on)',
                       placeholders={'mode': Placeholder('enum', '', 'SING', enum=('SING', 'CONT'))}, kind='set', readback='pm.trig.query', verified=True, ref=_rf(':PMETer:TRIGger', '41 and 42')),
    'pm.trig.query': Cmd('PMET1:TRIG?', 'Power meter trigger mode', kind='query', verified=True, ref=_rf(':PMETer:TRIGger?', 41)),
    'pm.zero': Cmd('PMET1:ZERO?', 'Zero the power sensor', 'Performs the input zero on the sensor (RF must be removed). Answers 0 for success and 1 for failure with an error message in the error queue. It ACTS, '
                   'so it is never retried and never overridable', kind='query', risk='locked', verified=True, ref=_rf(':PMETer:ZERO?', 41)),
    'pm.read': Cmd('PMET1:READ?', 'Power meter reading', 'The next reading; in single-trigger mode it triggers one and returns it. Whether the value follows UNIT:POW is UNVERIFIED; 9.91E+37 means none',
                   kind='query', verified=True, ref=_rf(':PMETer:READ?', 41)),
    'pm.idn': Cmd('PMET1:IDN?', 'Power sensor identity', 'Make, model, serial number, firmware version of the sensor; NONE, NONE, NONE, NONE when no sensor is fitted. An R&S NRP40T is UNVERIFIED '
                  '(the manual does not mention it)', kind='query', verified=True, ref=_rf(':PMETer:IDN?', 41)),
}
# Bench 2026-10-29 (tools/bench/records, step 5): the 96270A (firmware 1.17) sees the NRP40T on sensor 1 ("ROHDE&SCHWARZ,NRP40T,101033,03.50.25102101"); INST PMET,
# PMET1:FREQ 120E6 (-> 1.2E+8), PMET1:AVER AUTO, PMET1:TRIG CONT each read back; PMET1:ZERO? -> 0 after 10.6 s; PMET1:READ? -> -1.051E+1 for the 6060A at -10 dBm and
# -4.84E-1 at 0 dBm (dBm; the front panel showed -0.49); RF off: -3.7831E+1. In power-meter mode UNIT:POW? answers NONE, so the driver does not set or check it.
import dataclasses as _dc
for _k, _t in {'pm.inst.set': 'INST? -> PMET', 'pm.freq.set': 'PMET1:FREQ 120E6 -> 1.2E+8', 'pm.aver.set': 'AUTO -> AUTO', 'pm.trig.set': 'CONT -> CONT',
               'pm.zero': '0 after 10.6 s', 'pm.read': '-1.051E+1 at -10 dBm, -4.84E-1 at 0 dBm (dBm)', 'pm.idn': 'ROHDE&SCHWARZ,NRP40T,101033,03.50.25102101',
               'pm.unit.set': 'NOT USED: in power-meter mode UNIT:POW? answers NONE'}.items():
    PMETER_COMMANDS[_k] = _dc.replace(PMETER_COMMANDS[_k], ref=f'{PMETER_COMMANDS[_k].ref}; BENCH 2026-10-29 step 5: {_t}')
RF_COMMANDS.update(PMETER_COMMANDS)

# ---- Fluke 96270A FM mode (FM logical instrument): ADDED subset for the 6060A deviation-meter checks (owner, 2026-11-02). The command text was read on the RENDERED pages of the 96000 Series Remote
# Programmers Manual (Rev. 1, 10/14): INSTrument p. 32, POWer p. 35, FREQuency p. 36, FM subsystem p. 38, "FM Output" example p. 59 (INST FM; UNIT:POW DBM; POW; FREQ; FM:STATE 1;DEV 500.0E+3;
# INTernal:FREQ 27E3; OUTPUT ON). Nothing has run on hardware. NOT verified (flagged in the report): the unit of the FM:DEV? / FM:INT:FREQ? replies (the example sends Hz; the *RST column shows
# "10.0 kHz" / "1.0 kHz"), so each reply is compared in Hz and a mismatch is a loud error; the FM accuracy of the source (not read from the remote manual).
FM_COMMANDS = {
    'fm.inst.set': Cmd('INST FM', 'Select the FM instrument', 'FM is a logical instrument of the 96270A; selecting it puts the output into standby and makes the other logical instruments unavailable '
                       'until one is selected again', kind='set', readback='inst.query', verified=True, ref=_rf('INSTrument[:SELect] FM', 32)),
    'fm.freq.set': Cmd('FREQ {hz:.12g}', 'FM carrier frequency', 'Carrier of the FM instrument, Hz (9 MHz to 4.024 GHz, Operator Manual Table 3-26)', placeholders={'hz': Placeholder('float', '.12g', 3e7)},
                       kind='set', readback='freq.query', verified=True, ref=_rf('[:SOURce]:FREQuency[:CW|FIXed]', 36)),
    'fm.pow.set': Cmd('POW {dbm:.3f}', 'FM carrier level', 'dBm (UNIT:POW DBM is set and read back first)', placeholders={'dbm': Placeholder('float', '.3f', 7.0)}, kind='set',
                      readback='level.query', verified=True, ref=_rf('[:SOURce]:POWer[:LEVel]', 35)),
    'fm.state.set': Cmd('FM:STAT {on}', 'FM on', '1 = the output has an FM component, 0 = none', placeholders={'on': Placeholder('enum', '', '1', enum=('0', '1'))}, kind='set',
                        readback='fm.state.query', verified=True, ref=_rf('[:SOURce]:FM:STATe', 38)),
    'fm.state.query': Cmd('FM:STAT?', 'FM state', kind='query', verified=True, ref=_rf('[:SOURce]:FM:STATe?', 38)),
    'fm.dev.set': Cmd('FM:DEV {hz:.9g}', 'FM deviation', 'Peak deviation in Hz (the manual example sends 500.0E+3). Limits (Operator Manual Table 3-26): 10 Hz to 300 kHz at 9 to 31.4375 MHz, '
                      '750 kHz to 125.75 MHz, 0.12 % of the carrier above that', placeholders={'hz': Placeholder('float', '.9g', 1e4)}, kind='set', readback='fm.dev.query', verified=True,
                      ref=_rf('[:SOURce]:FM[:DEViation]', 38)),
    'fm.dev.query': Cmd('FM:DEV?', 'FM deviation', 'Unit of the reply is UNVERIFIED (compared in Hz)', kind='query', verified=True, ref=_rf('[:SOURce]:FM[:DEViation]?', 38)),
    'fm.rate.set': Cmd('FM:INT:FREQ {hz:.9g}', 'FM modulation rate', 'Internal modulation rate in Hz (1 Hz to 300 kHz); the example sends 27E3', placeholders={'hz': Placeholder('float', '.9g', 1e3)},
                       kind='set', readback='fm.rate.query', verified=True, ref=_rf('[:SOURce]:FM:INTernal:FREQuency', 38)),
    'fm.rate.query': Cmd('FM:INT:FREQ?', 'FM modulation rate', 'Unit of the reply is UNVERIFIED (compared in Hz)', kind='query', verified=True, ref=_rf('[:SOURce]:FM:INTernal:FREQuency?', 38)),
}
for _k, _c in list(FM_COMMANDS.items()):
    FM_COMMANDS[_k] = _dc.replace(_c, ref=f'{_c.ref}; example p. 59: INST FM, UNIT:POW DBM, POW, FREQ, FM:STATE 1;DEV;INT:FREQ, OUTPUT ON. NOT run on hardware')
RF_COMMANDS.update(FM_COMMANDS)
FM_MIN_HZ, FM_MAX_HZ_CARRIER = 9e6, 4.024e9           # Operator Manual Table 3-26
FM_RATE_MIN_HZ, FM_RATE_MAX_HZ = 1.0, 300e3


def fm_max_deviation_hz(carrier_hz: float) -> float:
    """The largest FM deviation the 96270A allows at a carrier (Operator Manual Table 3-26): 300 kHz to 31.4375 MHz, 750 kHz to 125.75 MHz, 0.12 % of the carrier above."""
    if carrier_hz <= 31.4375e6:
        return 300e3
    if carrier_hz <= 125.75e6:
        return 750e3
    return 0.0012 * carrier_hz
# ---- Fluke 96270A AM mode (AM logical instrument): ADDED subset for the HP 8591A sweep-time and span checks (owner, 2026-11-02: "sweep-time AM uses the 96270A internal AM"). The command text was read on the
# RENDERED pages of the 96000 Series Remote Programmers Manual (Rev. 1, 10/14): INSTrument p. 32, POWer p. 35, FREQuency p. 36, AM subsystem p. 37 ([:SOURce]:AM:STATe, AM[:DEPTh] (*RST 30.0 %),
# AM:INTernal:FREQuency (*RST 1000 Hz), AM:SHAPe {SINE|TRIangle|EXTernal}). Nothing has run on hardware. NOT verified (flagged in the report): the unit of the AM:DEPT? / AM:INT:FREQ? replies (the
# manual shows %, Hz in its *RST column; each reply is compared in %, Hz and a mismatch is a loud error), the AM accuracy of the source, and that the 96270A accepts a carrier of 500 MHz with the AM
# instrument selected (the Operator Manual limits the AM carrier to 50 kHz to 4.024 GHz and the modulation rate to 1 Hz to 220 kHz up to a 125.75 MHz carrier: not read here).
AM_COMMANDS = {
    'am.inst.set': Cmd('INST AM', 'Select the AM instrument', 'AM is a logical instrument of the 96270A; selecting it puts the output into standby and makes the other logical instruments unavailable '
                       'until one is selected again', kind='set', readback='inst.query', verified=True, ref=_rf('INSTrument[:SELect] AM', 32)),
    'am.freq.set': Cmd('FREQ {hz:.12g}', 'AM carrier frequency', 'Carrier of the AM instrument, Hz', placeholders={'hz': Placeholder('float', '.12g', 5e8)}, kind='set', readback='freq.query',
                       verified=True, ref=_rf('[:SOURce]:FREQuency[:CW|FIXed]', 36)),
    'am.pow.set': Cmd('POW {dbm:.3f}', 'AM carrier level', 'dBm (UNIT:POW DBM is set and read back first)', placeholders={'dbm': Placeholder('float', '.3f', -10.0)}, kind='set',
                      readback='level.query', verified=True, ref=_rf('[:SOURce]:POWer[:LEVel]', 35)),
    'am.state.set': Cmd('AM:STAT {on}', 'AM on', '1 = the output has an AM component, 0 = none', placeholders={'on': Placeholder('enum', '', '1', enum=('0', '1'))}, kind='set',
                        readback='am.state.query', verified=True, ref=_rf('[:SOURce]:AM:STATe', 37)),
    'am.state.query': Cmd('AM:STAT?', 'AM state', kind='query', verified=True, ref=_rf('[:SOURce]:AM:STATe?', 37)),
    'am.depth.set': Cmd('AM:DEPT {pct:.4g}', 'AM depth', 'Percent (*RST 30.0 %). 0.1 to 99 % per the Operator Manual (UNVERIFIED here)', placeholders={'pct': Placeholder('float', '.4g', 50.0)}, kind='set',
                        readback='am.depth.query', verified=True, ref=_rf('[:SOURce]:AM[:DEPTh]', 37)),
    'am.depth.query': Cmd('AM:DEPT?', 'AM depth', 'Unit of the reply is UNVERIFIED (compared in percent)', kind='query', verified=True, ref=_rf('[:SOURce]:AM[:DEPTh]?', 37)),
    'am.rate.set': Cmd('AM:INT:FREQ {hz:.9g}', 'AM modulation rate', 'Internal modulation rate in Hz (*RST 1000 Hz); 1 Hz to 220 kHz per the Operator Manual (UNVERIFIED here)',
                       placeholders={'hz': Placeholder('float', '.9g', 1e3)}, kind='set', readback='am.rate.query', verified=True, ref=_rf('[:SOURce]:AM:INTernal:FREQuency', 37)),
    'am.rate.query': Cmd('AM:INT:FREQ?', 'AM modulation rate', 'Unit of the reply is UNVERIFIED (compared in Hz)', kind='query', verified=True, ref=_rf('[:SOURce]:AM:INTernal:FREQuency?', 37)),
    'am.shape.set': Cmd('AM:SHAP {shape}', 'AM modulation shape', 'SINE (*RST), TRIangle or EXTernal',
                        placeholders={'shape': Placeholder('enum', '', 'TRI', enum=('SINE', 'TRI', 'EXT'))}, kind='set', readback='am.shape.query', verified=True, ref=_rf('[:SOURce]:AM:SHAPe', 37)),
    'am.shape.query': Cmd('AM:SHAP?', 'AM modulation shape', 'Reply text UNVERIFIED: matched on its first three letters', kind='query', verified=True, ref=_rf('[:SOURce]:AM:SHAPe?', 37)),
}
for _k, _c in list(AM_COMMANDS.items()):
    AM_COMMANDS[_k] = _dc.replace(_c, ref=f'{_c.ref}. NOT run on hardware')
RF_COMMANDS.update(AM_COMMANDS)
AM_RATE_MIN_HZ, AM_RATE_MAX_HZ, AM_DEPTH_MIN_PCT, AM_DEPTH_MAX_PCT = 1.0, 220e3, 0.1, 99.0          # Operator Manual (AM instrument), not read from the remote manual
AM_CARRIER_MIN_HZ, AM_CARRIER_MAX_HZ = 50e3, 4.024e9
PM_NO_READING = 9.0e37                       # :FETCh? answers 9.91E+37 when there is no reading (p. 41)

# ---- Fluke 96270A frequency counter (FCOunter logical instrument): ADDED for the 6060A GIDEP frequency points (owner, 2026-11-04: "use the frequency counter built into the 96270"). Read on the RENDERED
# pages of the owner's 96000 Series Remote Programmers Manual (96000__rpmeng0100.pdf, printed pages): INSTrument[:SELect] FCOunter p. 32, :FCOunter:RANGe p. 41 (1 = 50 MHz @ 10 kohm, 2 = 50 MHz @ 50 ohm,
# 3 = 300 MHz @ 50 ohm; *RST 1), :INIT:CONTinuous p. 42 (0 = single event; *RST 0), :TRIG:GATE p. 42 (0.2 | 2 | 20 | 80 s, rounded to the closest; *RST 2.0), MEASure? p. 43 (in SINGle mode it starts a
# measurement and returns it when complete; 9.91E37 when no measurement function is selected), [:SOUR]:ROSC:SOURce? and :LOCKed? p. 49 (EXTernal needs a reference within +/-0.3 ppm; LOCKed? = 1 when
# locked), example "Frequency Measurement - simple" p. 60 (INST FCO; TRIGGER:GATE 20; MEAS?). Product Specifications (Frequency Counter): rear 300 MHz Counter BNC, 0.9 to 310 MHz specified, 50 ohm above
# 50.5 MHz, 0.5 V pk-pk minimum, accuracy with an external reference = reference accuracy + 0.5 count (0.2 / 2 / 20 s gates). Nothing has run on hardware. NOT verified: the text of the INST?, FCO:RANG?,
# TRIG:GATE?, INIT:CONT? and ROSC:SOUR? replies (matched loosely: 'FCO' prefix, number, number, 0 / OFF, 'EXT' / 'ENAR' prefix), how long MEAS? takes beyond the gate (FCO_READ_MARGIN_S).
FCO_COMMANDS = {
    'fco.inst.set': Cmd('INST FCO', 'Select the frequency counter', 'FCOunter is a logical instrument of the 96270A; selecting it puts the output into standby and sets the rear BNC as the counter input '
                        '(INP:REAR, p. 34)', kind='set', readback='inst.query', verified=True, ref=_rf('INSTrument[:SELect] FCOunter; example p. 60', 32)),
    'fco.range.set': Cmd(':FCO:RANG {n}', 'Counter range', '1 = 50 MHz @ 10 kohm, 2 = 50 MHz @ 50 ohm, 3 = 300 MHz @ 50 ohm', placeholders={'n': Placeholder('enum', '', '3', enum=('1', '2', '3'))},
                         kind='set', readback='fco.range.query', verified=True, ref=_rf(':FCOunter:RANGe', 41)),
    'fco.range.query': Cmd(':FCO:RANG?', 'Counter range', kind='query', verified=True, ref=_rf(':FCOunter:RANGe?', 41)),
    'fco.gate.set': Cmd(':TRIG:GATE {s:g}', 'Counter gate time', '0.2, 2, 20 or 80 s', placeholders={'s': Placeholder('float', 'g', 2.0)}, kind='set', readback='fco.gate.query', verified=True,
                        ref=_rf(':TRIG:GATE', 42)),
    'fco.gate.query': Cmd(':TRIG:GATE?', 'Counter gate time', kind='query', verified=True, ref=_rf(':TRIG:GATE?', 42)),
    'fco.single.set': Cmd(':INIT:CONT 0', 'Single-event counter', 'One measurement per MEAS? (repetitive mode is 1)', kind='set', readback='fco.single.query', verified=True,
                          ref=_rf(':INIT:CONTinuous', 42)),
    'fco.single.query': Cmd(':INIT:CONT?', 'Counter trigger mode', kind='query', verified=True, ref=_rf(':INIT:CONTinuous?', 42)),
    'fco.measure': Cmd('MEAS?', 'Counter reading', 'In single mode a measurement is started and returned when complete (Hz); 9.91E37 = no reading', kind='query', verified=True,
                       ref=_rf('MEASure?', 43)),
    'rosc.source.query': Cmd(':ROSC:SOUR?', 'Reference source', 'INTernal or EXTernal (ENARow = EXTernal)', kind='query', verified=True, ref=_rf('[:SOUR]:ROSC:SOURce?', 49)),
    'rosc.locked.query': Cmd(':ROSC:LOCK?', 'Reference locked', '1 when locked to the selected reference', kind='query', verified=True, ref=_rf('[:SOUR]:ROSC:LOCKed?', 49)),
}
for _k, _c in list(FCO_COMMANDS.items()):
    FCO_COMMANDS[_k] = _dc.replace(_c, ref=f'{_c.ref}. NOT run on hardware')
RF_COMMANDS.update(FCO_COMMANDS)
FCO_RANGES = {1: (0.9e6, 50.5e6), 2: (0.9e6, 50.5e6), 3: (50.5e6, 310e6)}     # Product Specifications: bands 0.9 to 50.5 MHz, >50.5 to 310 MHz (50 ohm)
FCO_GATES = (0.2, 2.0, 20.0, 80.0)
FCO_READ_MARGIN_S = 10.0                     # MEAS? answers within gate + this (a choice of this driver; the manual gives no figure)


def _num(reply: str):
    """'3', '+3', '2.0', '2.00000E+00' -> float; None when the reply holds no number."""
    try:
        return float(str(reply).strip().strip('"').split(',')[0].split()[0])
    except (ValueError, IndexError):
        return None


def _bool_reply(reply: str) -> bool:
    r = reply.strip().upper()
    if r in ('1', 'ON'):
        return True
    if r in ('0', 'OFF'):
        return False
    raise InstrumentError(f'unexpected boolean reply {reply!r}')


class Fluke96270A(Instrument):
    MODEL = 'Fluke 96270A'
    IDN_MATCH = ('96270',)          # *IDN? reply is "Fluke,96270A,<serial>,<firmware>" (p57); a plain 'FLUKE' would also accept a 5560A
    DEFAULT_TIMEOUT = 15.0
    MAX_HZ = 6.2e9                  # limit for the MDO4000C RF tests, not the instrument's own range
    COMMANDS = RF_COMMANDS

    output_off_confirmed = False

    def connect(self):
        """Open, clear status, then put the source in a known state: SINE instrument, levels in dBm, no offsets, output off.
        Selecting the instrument also puts the output into standby (p38). Each setting is read back."""
        self.open(verify_model=True)
        self.send('status.clear')
        self._apply_known_state()
        return self

    def _apply_known_state(self):
        """SINE instrument, levels in dBm, no offsets, output off (each read back). Run at connect and again after a reset."""
        self._set_and_check('inst.set', 'inst.query', lambda r: r.strip().strip('"').upper() == 'SINE', 'instrument SINE')
        self._set_and_check('unit.set', 'unit.query', lambda r: r.strip().strip('"').upper() == 'DBM', 'power units DBM')
        self._set_and_check('poffs.set', 'poffs.query', lambda r: not _bool_reply(r), 'power offset off')
        self._set_and_check('foffs.set', 'foffs.query', lambda r: not _bool_reply(r), 'frequency offset off')
        self.output(False)

    def _reset_extra(self):
        return [('known state again (SINE, dBm, offsets off, output OFF)', self._apply_known_state)]

    def _set_and_check(self, key, query, ok, what):
        self.send(key)
        reply = self.ask(query)
        if not ok(reply):
            raise InstrumentError(f'96270A {what}: set {cmdreg.render(self._registry()[key])!r}, reports {reply.strip()!r}')
        self.check_error(what)

    def check_error(self, context=''):
        """Raise if the source rejected a command. SYST:ERR? returns 0 when the queue is empty."""
        reply = self.ask('err.query').strip()
        code = reply.split(',')[0].strip().lstrip('+')
        try:
            failed = int(float(code)) != 0
        except ValueError:
            failed = True
        if failed:
            raise InstrumentError(f'96270A rejected the setting{" (" + context + ")" if context else ""}: {reply}')

    def set_rf(self, frequency_hz, level_dbm):
        if frequency_hz > self.MAX_HZ:
            raise InstrumentError(f'{frequency_hz / 1e9:g} GHz is above the {self.MODEL} range')
        self.send('freq.level', f=frequency_hz, p=level_dbm)
        self.check_error(f'{frequency_hz:g} Hz, {level_dbm:g} dBm')
        got = float(self.ask('freq.query').strip().split()[0])
        if not math.isclose(got, frequency_hz, rel_tol=1e-6):
            raise InstrumentError(f'96270A frequency set {frequency_hz:g}, reports {got:g}')
        lvl = float(self.ask('level.query').strip().split()[0])
        if abs(lvl - level_dbm) > 0.01:
            raise InstrumentError(f'96270A level set {level_dbm:g} dBm, reports {lvl:g} dBm')

    def output(self, on: bool):
        """OUTP ON/OFF, then read OUTP? and compare. Not confirming OFF is a SafetyError."""
        self.send('outp.on' if on else 'outp.off')
        state = _bool_reply(self.ask('outp.query'))
        if state != on:
            if on:
                raise InstrumentError('96270A did not confirm output ON')
            raise SafetyError('96270A did not confirm output OFF; check the front panel')

    def cleanup(self):
        """Best effort: never leave the output live. Never raises."""
        try:
            self.send('outp.off')
            self.output_off_confirmed = not _bool_reply(self.ask('outp.query'))
        except Exception:
            self.output_off_confirmed = False

    # ---- power-meter mode (ADDED; the Rohde & Schwarz NRP40T sensor is UNVERIFIED, see PMETER_COMMANDS) ---------------------------------------------------------
    PM_MIN_DBM, PM_MAX_DBM = -120.0, 50.0        # a reading outside this is not taken as dBm (a choice of this driver: the manual does not say whether READ? follows UNIT:POW)

    def select_power_meter(self, frequency_hz: float | None = None, average: str = 'AUTO', single: bool = False) -> str:
        """INST PMET (the output goes to standby, p. 32), PMET1:TRIG CONT (the bench-proven mode; SING is UNVERIFIED) or SING, PMET:AVER, PMET:FREQ (each read back and compared), then PMET:IDN?: it must name a sensor
        (NONE, NONE, NONE, NONE means none is fitted). Returns the sensor identity text (an NRP40T is UNVERIFIED). Use select_sine() to go back to the source."""
        self.send('pm.inst.set')
        reply = self.ask('inst.query').strip().strip('"').upper()
        if not reply.startswith('PMET'):
            raise InstrumentError(f'96270A did not select the power meter: INST? answered {reply!r}')
        # no UNIT:POW here: in power-meter mode UNIT:POW? answers NONE and PMET1:READ? is in dBm (bench 2026-10-29, step 5)
        mode = 'SING' if single else 'CONT'
        self.send('pm.trig.set', mode=mode)
        reply = self.ask('pm.trig.query').strip().strip('"').upper()
        if not reply.startswith(mode[:4]):
            raise InstrumentError(f'96270A power-meter trigger {mode} was not accepted: PMET:TRIG? answered {reply!r}')
        self.send('pm.aver.set', n=str(average))
        reply = self.ask('pm.aver.query').strip().strip('"').upper()
        if reply != str(average).upper() and not (reply.replace('+', '').replace('.0', '') == str(average)):
            raise InstrumentError(f'96270A power-meter averaging {average} was not accepted: PMET:AVER? answered {reply!r}')
        if frequency_hz is not None:
            self.send('pm.freq.set', hz=float(frequency_hz))
            got = float(self.ask('pm.freq.query').strip().split()[0])
            if not math.isclose(got, frequency_hz, rel_tol=1e-6):
                raise InstrumentError(f'96270A power-meter frequency set {frequency_hz:g}, reports {got:g}')
        ident = self.ask('pm.idn').strip()
        if ident.replace(' ', '').upper().startswith('NONE'):
            raise InstrumentError(f'96270A has no power sensor fitted (PMET:IDN? answered {ident!r})')
        self.check_error('power meter setup')
        return ident

    def setup_fm(self, carrier_hz: float, level_dbm: float, deviation_hz: float, rate_hz: float) -> None:
        """INST FM (the output goes to standby, p. 32), UNIT:POW DBM, POW, FREQ, FM:STAT 1, FM:DEV, FM:INT:FREQ, each read back and compared, then SYST:ERR?. The output stays OFF: call output(True).
        Refuses a carrier, rate or deviation outside the limits of Operator Manual Table 3-26 before anything is sent. Never retried. Use select_sine() to go back to the source."""
        if not FM_MIN_HZ <= carrier_hz <= FM_MAX_HZ_CARRIER:
            raise InstrumentError(f'96270A FM carrier {carrier_hz / 1e6:g} MHz is outside 9 MHz to 4.024 GHz')
        if not FM_RATE_MIN_HZ <= rate_hz <= FM_RATE_MAX_HZ:
            raise InstrumentError(f'96270A FM rate {rate_hz:g} Hz is outside 1 Hz to 300 kHz')
        top = fm_max_deviation_hz(carrier_hz)
        if not 10.0 <= deviation_hz <= top + 1e-6:
            raise InstrumentError(f'96270A FM deviation {deviation_hz / 1e3:g} kHz is outside 0.01 to {top / 1e3:g} kHz at {carrier_hz / 1e6:g} MHz (Operator Manual Table 3-26)')
        self.output(False)
        self.send('fm.inst.set')
        reply = self.ask('inst.query').strip().strip('"').upper()
        if reply != 'FM':
            raise InstrumentError(f'96270A did not select the FM instrument: INST? answered {reply!r}')
        self._set_and_check('unit.set', 'unit.query', lambda r: r.strip().strip('"').upper() == 'DBM', 'power units DBM (FM)')
        self.send('fm.pow.set', dbm=level_dbm)
        lvl = float(self.ask('level.query').strip().split()[0])
        if abs(lvl - level_dbm) > 0.01:
            raise InstrumentError(f'96270A FM level set {level_dbm:g} dBm, reports {lvl:g} dBm')
        self.send('fm.freq.set', hz=carrier_hz)
        got = float(self.ask('freq.query').strip().split()[0])
        if not math.isclose(got, carrier_hz, rel_tol=1e-6):
            raise InstrumentError(f'96270A FM carrier set {carrier_hz:g}, reports {got:g}')
        self.send('fm.state.set', on='1')
        if not _bool_reply(self.ask('fm.state.query')):
            raise InstrumentError('96270A did not confirm FM on (FM:STAT? answered off)')
        self.send('fm.dev.set', hz=deviation_hz)
        got = float(self.ask('fm.dev.query').strip().split()[0])
        if not math.isclose(got, deviation_hz, rel_tol=1e-4):
            raise InstrumentError(f'96270A FM deviation set {deviation_hz:g} Hz, reports {got:g} (UNVERIFIED: the unit of the FM:DEV? reply is not in the manual)')
        self.send('fm.rate.set', hz=rate_hz)
        got = float(self.ask('fm.rate.query').strip().split()[0])
        if not math.isclose(got, rate_hz, rel_tol=1e-4):
            raise InstrumentError(f'96270A FM rate set {rate_hz:g} Hz, reports {got:g} (UNVERIFIED: the unit of the FM:INT:FREQ? reply is not in the manual)')
        self.check_error('FM setup')

    def setup_am(self, carrier_hz: float, level_dbm: float, depth_pct: float, rate_hz: float, shape: str = 'TRI') -> None:
        """INST AM (the output goes to standby, p. 32), UNIT:POW DBM, POW, FREQ, AM:SHAP, AM:STAT 1, AM:DEPT, AM:INT:FREQ, each read back and compared, then SYST:ERR?. The output stays OFF: call output(True).
        Refuses a carrier, rate or depth outside the limits of the Operator Manual before anything is sent (a rate below 1 Hz cannot be made). Never retried. select_sine() goes back to the source."""
        if not AM_CARRIER_MIN_HZ <= carrier_hz <= AM_CARRIER_MAX_HZ:
            raise InstrumentError(f'96270A AM carrier {carrier_hz / 1e6:g} MHz is outside 50 kHz to 4.024 GHz')
        if not AM_RATE_MIN_HZ <= rate_hz <= AM_RATE_MAX_HZ:
            raise InstrumentError(f'96270A AM rate {rate_hz:g} Hz is outside 1 Hz to 220 kHz')
        if not AM_DEPTH_MIN_PCT <= depth_pct <= AM_DEPTH_MAX_PCT:
            raise InstrumentError(f'96270A AM depth {depth_pct:g} % is outside 0.1 to 99 %')
        self.output(False)
        self.send('am.inst.set')
        reply = self.ask('inst.query').strip().strip('"').upper()
        if reply != 'AM':
            raise InstrumentError(f'96270A did not select the AM instrument: INST? answered {reply!r}')
        self._set_and_check('unit.set', 'unit.query', lambda r: r.strip().strip('"').upper() == 'DBM', 'power units DBM (AM)')
        self.send('am.pow.set', dbm=level_dbm)
        lvl = float(self.ask('level.query').strip().split()[0])
        if abs(lvl - level_dbm) > 0.01:
            raise InstrumentError(f'96270A AM level set {level_dbm:g} dBm, reports {lvl:g} dBm')
        self.send('am.freq.set', hz=carrier_hz)
        got = float(self.ask('freq.query').strip().split()[0])
        if not math.isclose(got, carrier_hz, rel_tol=1e-6):
            raise InstrumentError(f'96270A AM carrier set {carrier_hz:g}, reports {got:g}')
        self.send('am.shape.set', shape=shape)
        reply = self.ask('am.shape.query').strip().strip('"').upper()
        if reply[:3] != shape.upper()[:3]:
            raise InstrumentError(f'96270A AM shape {shape} was not accepted: AM:SHAP? answered {reply!r}')
        self.send('am.state.set', on='1')
        if not _bool_reply(self.ask('am.state.query')):
            raise InstrumentError('96270A did not confirm AM on (AM:STAT? answered off)')
        self.send('am.depth.set', pct=depth_pct)
        got = float(self.ask('am.depth.query').strip().split()[0])
        if not math.isclose(got, depth_pct, rel_tol=1e-4):
            raise InstrumentError(f'96270A AM depth set {depth_pct:g} %, reports {got:g} (UNVERIFIED: the unit of the AM:DEPT? reply is not in the manual)')
        self.send('am.rate.set', hz=rate_hz)
        got = float(self.ask('am.rate.query').strip().split()[0])
        if not math.isclose(got, rate_hz, rel_tol=1e-4):
            raise InstrumentError(f'96270A AM rate set {rate_hz:g} Hz, reports {got:g} (UNVERIFIED: the unit of the AM:INT:FREQ? reply is not in the manual)')
        self.check_error('AM setup')

    def measure_counter_hz(self, range_n: int, gate_s: float, expect_hz: float | None = None, require_ext_ref: bool = True) -> float:
        """One frequency-counter reading in Hz (rear 300 MHz Counter BNC): output OFF, INST FCO, the reference must be EXTernal and locked (the lab GPS 10 MHz; on the internal reference the
        counter's 0.05 ppm is 15 Hz at 300 MHz), FCO:RANG, TRIG:GATE, INIT:CONT 0 (each read back), SYST:ERR?, then MEAS? with the timeout raised to gate + FCO_READ_MARGIN_S. 9.91E37 and a
        reading far from `expect_hz` (more than 1 %: the wrong signal or no signal) raise InstrumentError. The counter stays selected: call select_sine() afterwards. Never retried."""
        range_n = int(range_n)
        if range_n not in FCO_RANGES:
            raise InstrumentError(f'96270A counter range {range_n} is not 1, 2 or 3 (p. 41)')
        if float(gate_s) not in FCO_GATES:
            raise InstrumentError(f'96270A counter gate {gate_s:g} s is not 0.2, 2, 20 or 80 s (p. 42)')
        if expect_hz is not None:
            lo, hi = FCO_RANGES[range_n]
            if not lo <= expect_hz <= hi:
                raise InstrumentError(f'{expect_hz / 1e6:g} MHz is outside counter range {range_n} ({lo / 1e6:g} to {hi / 1e6:g} MHz, 96000 Series Product Specifications)')
        self.output(False)
        self.send('fco.inst.set')
        reply = self.ask('inst.query').strip().strip('"').upper()
        if not reply.startswith('FCO'):
            raise InstrumentError(f'96270A did not select the frequency counter: INST? answered {reply!r}')
        if require_ext_ref:
            src = self.ask('rosc.source.query').strip().strip('"').upper()
            if not src.startswith(('EXT', 'ENAR')):
                raise InstrumentError(f'96270A reference is {src!r}, not EXTernal: set the 96270A to its external 10 MHz reference (the lab GPS) for the frequency points. '
                                      'On its internal reference the counter is +/-0.05 ppm, 15 Hz at 300 MHz, against +/-10 Hz limits.')
            if not _bool_reply(self.ask('rosc.locked.query')):
                raise InstrumentError('96270A is not locked to its external 10 MHz reference (ROSC:LOCK? = 0): check the GPS 10 MHz at the 96270A reference input.')
        self.send('fco.range.set', n=str(range_n))
        got = self.ask('fco.range.query').strip()
        if _num(got) != range_n:
            raise InstrumentError(f'96270A counter range set {range_n}, FCO:RANG? answered {got!r}')
        self.send('fco.gate.set', s=float(gate_s))
        got = self.ask('fco.gate.query').strip()
        if _num(got) is None or not math.isclose(_num(got), float(gate_s), rel_tol=1e-6):
            raise InstrumentError(f'96270A counter gate set {gate_s:g} s, TRIG:GATE? answered {got!r}')
        self.send('fco.single.set')
        if _bool_reply(self.ask('fco.single.query')):
            raise InstrumentError('96270A counter did not go to single-event mode (INIT:CONT? answered on)')
        self.check_error('frequency counter setup')
        prev = getattr(self.t, 'timeout', None)
        self.t.set_timeout(max(float(gate_s) + FCO_READ_MARGIN_S, prev or 0.0))
        try:
            raw = self.ask('fco.measure').strip()
        finally:
            self.t.set_timeout(prev if prev is not None else self.DEFAULT_TIMEOUT)
        value = _num(raw)
        if value is None or not math.isfinite(value) or abs(value) >= PM_NO_READING:
            raise InstrumentError(f'96270A counter has no reading ({raw!r}): is the signal at the rear 300 MHz Counter BNC, at least 0.5 V pk-pk?')
        if expect_hz is not None and abs(value - expect_hz) > 0.01 * expect_hz:
            raise InstrumentError(f'96270A counter read {value:.10g} Hz, far from the expected {expect_hz:.10g} Hz: check the counter cable and the 6060A RF output')
        self.check_error('frequency counter reading')
        return value

    def select_sine(self):
        """Back to the leveled-sine source: the known state again (SINE, dBm, offsets off, output OFF), each read back."""
        self._apply_known_state()

    def zero(self) -> None:
        """PMET:ZERO? (RF removed from the sensor): 0 = zeroed. It ACTS on the sensor, so it is asked once and never retried. A 1 raises InstrumentError with the error-queue entry."""
        reply = self.ask('pm.zero').strip()
        if reply.lstrip('+') not in ('0', '0.0'):
            try:
                detail = self.ask('err.query').strip()
            except Exception as exc:
                detail = f'(error queue unreadable: {exc})'
            raise InstrumentError(f'96270A power sensor zero failed: PMET:ZERO? answered {reply!r}; error queue: {detail}')

    def read_dbm(self) -> float:
        """PMET:READ? as dBm. 9.91E+37 (no reading) and a value that is not plausible in dBm (the manual does not say the reading follows UNIT:POW) raise InstrumentError."""
        raw = self.ask('pm.read').strip()
        try:
            value = float(raw.split(',')[0].split()[0])
        except (ValueError, IndexError):
            raise InstrumentError(f'96270A unreadable power-meter reading {raw!r}') from None
        if not math.isfinite(value) or abs(value) >= PM_NO_READING:
            raise InstrumentError(f'96270A has no power-meter reading ({raw})')
        if not self.PM_MIN_DBM <= value <= self.PM_MAX_DBM:
            raise InstrumentError(f'96270A power-meter reading {value:g} is not plausible in dBm (is the unit W? UNVERIFIED that READ? follows UNIT:POW)')
        return value


class AgilentAFG(Instrument):
    MODEL = 'Agilent 33220A / 33250A'
    IDN_MATCH = ('33220', '33250')
    DEFAULT_TIMEOUT = 10.0
    MAX_SINE_HZ = {'33220': 20e6, '33250': 80e6}     # sine ranges: 33220A / 33250A Service Guide specifications
    COMMANDS = AFG_COMMANDS

    def connect(self):
        self.open(verify_model=True)
        self.send('status.clear')
        self.idn = self.identify()
        self.kind = '33250' if '33250' in self.idn else '33220'
        return self

    def _reset_extra(self):
        def off():
            self.send('outp.off')
            if _bool_reply(self.ask('outp.query')):
                raise SafetyError('33220A / 33250A did not confirm output OFF after the reset; check the front panel')
        return [('output OFF confirmed (OUTPut OFF, OUTPut?)', off)]

    @property
    def max_hz(self):
        return self.MAX_SINE_HZ[self.kind]

    def sine(self, frequency_hz, vpp, load='50'):
        """Sine wave, amplitude in Vpp into the stated load, offset 0 V. Output stays OFF until output(True)."""
        if frequency_hz > self.max_hz:
            raise InstrumentError(f'{frequency_hz / 1e6:g} MHz is above the {self.kind} sine range ({self.max_hz / 1e6:g} MHz)')
        self.send('outp.off')
        self.send('load.50' if load == '50' else 'load.inf')
        self.send('apply.sin', frequency_hz=frequency_hz, vpp=vpp)
        self._verify(frequency_hz, vpp)

    def square(self, frequency_hz, vpp, load='50'):
        self.send('outp.off')
        self.send('load.50' if load == '50' else 'load.inf')
        self.send('apply.squ', frequency_hz=frequency_hz, vpp=vpp)
        self._verify(frequency_hz, vpp)

    def _verify(self, frequency_hz, vpp):
        f = float(self.ask('freq.query').strip())
        a = float(self.ask('volt.query').strip())
        if not math.isclose(f, frequency_hz, rel_tol=1e-6):
            raise InstrumentError(f'{self.kind} frequency set {frequency_hz:g}, reports {f:g}')
        if not math.isclose(a, vpp, rel_tol=1e-3, abs_tol=1e-4):
            raise InstrumentError(f'{self.kind} amplitude set {vpp:g} Vpp, reports {a:g}')
        err = self.ask('err.query').strip()
        if not err.startswith(('+0', '0')):
            raise InstrumentError(f'{self.kind} rejected the setting: {err}')

    def output(self, on: bool):
        self.send('outp.on' if on else 'outp.off')

    def cleanup(self):
        try:
            self.send('outp.off')
        except Exception:
            pass


class ReferenceMeter(Instrument):
    """Generic SCPI DMM / counter for the AFG checks."""
    MODEL = 'SCPI reference meter'
    IDN_MATCH = ()
    DEFAULT_TIMEOUT = 20.0
    COMMANDS = METER_COMMANDS

    def connect(self):
        self.open(verify_model=False)
        self.send('status.clear')
        self.idn = self.identify()
        return self

    def _num(self, key):
        raw = self.ask(key).strip().split(',')[0]
        v = float(raw)
        if not math.isfinite(v) or abs(v) > 1e35:
            raise InstrumentError(f'Invalid reading from {cmdreg.render(self._registry()[key])}: {raw}')
        return v

    def frequency(self):
        return self._num('freq.meas')

    def ac_rms(self):
        self.send('conf.vac')
        self.send('vac.band')
        time.sleep(3.0)
        return self._num('read')

    def power(self):
        """Power meter reading in dBm."""
        return self._num('power.meas')

    def dc(self):
        self.send('conf.vdc')
        time.sleep(1.0)
        return self._num('read')
