"""Tektronix TDS2000C / TDS1000C-EDU digital storage oscilloscope over USB (USBTMC / VISA).

Command strings follow the TBS1000/B/EDU, TDS2000/B/C, TDS1000/B/C-EDU, TDS200, TPS2000/B Series Programmer Manual (077-0444-03 Rev B);
each method names the manual page of the command it uses (page numbers are the printed "2-nn" numbers).  Writes are never retried;
every setting is read back and compared, and the event status register is checked after each group of settings (check_errors) so a
rejected command stops the run instead of producing a reading for the wrong set-up.

The scope does not execute commands while a self calibration runs (p. 2-48), so self_cal() waits on one long query and is never repeated.
"""
from __future__ import annotations

import math
import re
import time

from .base import Instrument, InstrumentError

MODEL_RE = re.compile(r'TDS\s*(\d{4}C(?:-EDU)?)', re.I)
FOUR_CHANNEL = ('2004C', '2014C', '2024C')
OVERFLOW = 9.9e37            # "no valid measurement" (p. 2-144)


def _last_number(reply: str) -> float:
    """The number at the end of a reply, with or without a command header (HEADer ON replies ':CH1:SCALE 1.0E-1')."""
    token = reply.strip().replace(';', ' ').split()[-1]
    return float(token)


def _last_word(reply: str) -> str:
    return reply.strip().replace(';', ' ').split()[-1].strip('"').upper()


class TektronixTDS2000C(Instrument):
    MODEL = 'Tektronix TDS2000C / TDS1000C-EDU'
    IDN_MATCH = ('TDS',)
    DEFAULT_TIMEOUT = 15.0
    SELF_CAL_TIMEOUT = 360.0        # "can take several minutes" (p. 2-48)
    model = ''
    channels = 2

    # ---- connection ---------------------------------------------------------------------------------------------------
    def connect(self):
        self.open(verify_model=True)
        self.write('*CLS')
        self.write('HEADer OFF')
        self.write('VERBose OFF')
        self.idn = self.identify()
        self.model = self.model_from_idn(self.idn)
        self.channels = 4 if self.model in FOUR_CHANNEL else 2
        return self

    @staticmethod
    def model_from_idn(idn: str) -> str:
        """'2024C' from 'TEKTRONIX,TDS 2024C,C012345,CF:91.1CT FV:v24.00'; '' when the model cannot be read."""
        m = MODEL_RE.search(idn or '')
        return m.group(1).upper() if m else ''

    def cleanup(self):
        """The scope has no outputs; nothing to turn off."""

    # ---- helpers --------------------------------------------------------------------------------------------------------
    def opc(self, timeout=None):
        if timeout:
            self.t.set_timeout(timeout)
        try:
            self.query('*OPC?')                      # p. 2-152
        finally:
            if timeout:
                self.t.set_timeout(self.DEFAULT_TIMEOUT)

    def check_errors(self, context=''):
        """Raise if the event status register reports a command / execution / device / query error since the last check (*ESR? clears it)."""
        esr = int(_last_number(self.query('*ESR?')))             # p. 2-84
        if esr & 0b00111100:
            try:
                detail = self.query('EVMsg?').strip()           # p. 2-85
            except Exception:
                detail = ''
            raise InstrumentError(f'The oscilloscope rejected a command{" (" + context + ")" if context else ""}: ESR={esr} {detail}')

    def set_verified(self, cmd_set, cmd_query, value, rel=1e-3, abs_=1e-12):
        """Write a numeric setting, read it back, compare. Never retried."""
        self.write(f'{cmd_set} {value:.9g}')
        got = _last_number(self.query(cmd_query))
        if not math.isclose(got, value, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{cmd_set}: set {value:g}, instrument reports {got:g}')
        return got

    def set_enum_verified(self, cmd_set, cmd_query, value, match=None):
        """Write an enumerated setting, read it back, compare the first letters (replies are abbreviated or upper case)."""
        self.write(f'{cmd_set} {value}')
        got = _last_word(self.query(cmd_query))
        want = (match or value).upper()
        if not (got.startswith(want[:3]) or want.startswith(got[:3])):
            raise InstrumentError(f'{cmd_set}: set {value}, instrument reports {got}')
        return got

    # ---- state ----------------------------------------------------------------------------------------------------------
    def default_setup(self):
        """FACtory (p. 2-87), the equivalent of the Default Setup button. It turns HEADer ON again, so HEADer OFF is re-sent."""
        self.write('FACtory')
        self.opc(60)
        self.write('HEADer OFF')
        self.write('VERBose OFF')
        self.check_errors('FACtory')

    def run_self_test(self):
        """Result of the power-on diagnostics: (passed, log text). DIAg:RESUlt:FLAg? (p. 2-78) and DIAg:RESUlt:LOG? (p. 2-79)."""
        flag = _last_word(self.query('DIAg:RESUlt:FLAg?'))
        try:
            log = self.query('DIAg:RESUlt:LOG?').strip()
        except Exception:
            log = ''
        return flag == 'PASS', log

    def self_cal(self):
        """Do Self Cal: *CAL? performs it and returns 0 when no errors were found (p. 2-48); CALibrate:STATUS? must then say PASS (p. 2-51).
        All signals must be disconnected first. Not retried (it is an action, not just a query)."""
        self.t.set_timeout(self.SELF_CAL_TIMEOUT)
        try:
            result = int(_last_number(self.query('*CAL?')))
        finally:
            self.t.set_timeout(self.DEFAULT_TIMEOUT)
        status = _last_word(self.query('CALibrate:STATUS?'))
        return result == 0 and status == 'PASS', f'*CAL? = {result}, CALibrate:STATUS? = {status}'

    # ---- vertical -------------------------------------------------------------------------------------------------------
    def select_only(self, ch):
        """Display channel ch (SELect:CH<x>, p. 2-172) and remove the others; the wanted channel is switched on first so one is always displayed."""
        self.write(f'SELect:CH{ch} ON')
        for n in range(1, self.channels + 1):
            if n != ch:
                self.write(f'SELect:CH{n} OFF')

    def channel(self, ch, vscale=None, position=0.0, probe=1, coupling='DC', bw_limit=False):
        """Probe 1X, DC coupling, full bandwidth, volts/div and position (divisions). Each read back. Position steps are coarse, so the
        read-back tolerance is 0.05 division (p. 2-55)."""
        self.set_enum_verified(f'CH{ch}:COUPling', f'CH{ch}:COUPling?', coupling)
        self.set_enum_verified(f'CH{ch}:BANdwidth', f'CH{ch}:BANdwidth?', 'ON' if bw_limit else 'OFF')
        self.set_verified(f'CH{ch}:PRObe', f'CH{ch}:PRObe?', float(probe), rel=1e-6)
        if vscale is not None:
            self.set_verified(f'CH{ch}:SCAle', f'CH{ch}:SCAle?', vscale, rel=1e-3)
        if position is not None:
            self.set_verified(f'CH{ch}:POSition', f'CH{ch}:POSition?', position, abs_=0.05)

    def position(self, ch, divisions):
        return self.set_verified(f'CH{ch}:POSition', f'CH{ch}:POSition?', divisions, abs_=0.05)

    # ---- acquisition ----------------------------------------------------------------------------------------------------
    def acquire_mode(self, mode, averages=16):
        """SAMple or AVErage (p. 2-40); averages 4, 16, 64 or 128 (p. 2-41)."""
        self.set_enum_verified('ACQuire:MODe', 'ACQuire:MODe?', mode)
        if mode.upper().startswith('AVE'):
            self.set_verified('ACQuire:NUMAVg', 'ACQuire:NUMAVg?', float(averages), rel=1e-6)
        self.write('ACQuire:STOPAfter RUNSTop')
        self.run()

    def run(self):
        """ACQuire:STATE RUN restarts the acquisition and resets the acquisition count (p. 2-42)."""
        self.write('ACQuire:STATE RUN')

    def num_acq(self):
        return int(_last_number(self.query_retry('ACQuire:NUMACq?')))       # p. 2-41 (read-only, retry allowed)

    def wait_acquisitions(self, count, timeout=30.0, poll=0.1):
        """Restart the acquisition and wait until at least `count` acquisitions have completed (averaging needs the full count)."""
        self.run()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.num_acq() >= count:
                return
            time.sleep(poll)
        raise InstrumentError(f'The oscilloscope completed fewer than {count} acquisitions in {timeout:g} s')

    # ---- horizontal ----------------------------------------------------------------------------------------------------
    def timebase(self, seconds_per_div):
        """HORizontal:MAIn:SCAle (p. 2-112)."""
        self.set_verified('HORizontal:MAIn:SCAle', 'HORizontal:MAIn:SCAle?', seconds_per_div, rel=1e-3)

    def horizontal_position(self, seconds):
        """HORizontal:MAIn:POSition (p. 2-112). Read back with a 1 ns floor."""
        self.set_verified('HORizontal:MAIn:POSition', 'HORizontal:MAIn:POSition?', seconds, rel=1e-6, abs_=1e-9)

    # ---- trigger --------------------------------------------------------------------------------------------------------
    def trigger_edge(self, source, slope='RISe', mode='AUTO', coupling='NOISErej'):
        """Edge trigger (TRIGger:MAIn:..., pp. 2-194 to 2-198). source CH1..CH4 or EXT."""
        self.write('TRIGger:MAIn:TYPe EDGE')
        self.set_enum_verified('TRIGger:MAIn:EDGE:SOUrce', 'TRIGger:MAIn:EDGE:SOUrce?', source)
        self.set_enum_verified('TRIGger:MAIn:EDGE:SLOpe', 'TRIGger:MAIn:EDGE:SLOpe?', slope)
        self.set_enum_verified('TRIGger:MAIn:EDGE:COUPling', 'TRIGger:MAIn:EDGE:COUPling?', coupling)
        self.trigger_mode(mode)

    def trigger_mode(self, mode):
        self.set_enum_verified('TRIGger:MAIn:MODe', 'TRIGger:MAIn:MODe?', mode)

    def set_level_50(self):
        """Set To 50%: TRIGger:MAIn SETLevel (p. 2-194). Ignored with event 221 if the acquisition is stopped, so it runs the acquisition first."""
        self.run()
        self.write('TRIGger:MAIn SETLevel')
        self.check_errors('TRIGger:MAIn SETLevel')

    def trigger_state(self):
        """ARMED, READY, TRIGGER, AUTO or SCAN (p. 2-205)."""
        return _last_word(self.query_retry('TRIGger:STATE?'))

    # ---- measurements ---------------------------------------------------------------------------------------------------
    def measure_setup(self, mtype, ch):
        """Immediate measurement source and type (pp. 2-138 and 2-139): MEAN or PK2pk."""
        self.set_enum_verified('MEASUrement:IMMed:SOUrce', 'MEASUrement:IMMed:SOUrce?', f'CH{ch}')
        self.set_enum_verified('MEASUrement:IMMed:TYPe', 'MEASUrement:IMMed:TYPe?', mtype)

    def meas_value(self):
        """MEASUrement:IMMed:VALue? (p. 2-144). 9.9E37 means no valid measurement."""
        v = _last_number(self.query('MEASUrement:IMMed:VALue?'))
        if not math.isfinite(v) or abs(v) >= OVERFLOW:
            raise InstrumentError(f'The oscilloscope returned no valid measurement ({v:g}); check the channel is displayed and the signal is connected')
        return v

    def measure(self, mtype, ch, count=16, timeout=40.0):
        """Set up the measurement, let `count` acquisitions complete, read one value."""
        self.measure_setup(mtype, ch)
        self.wait_acquisitions(count, timeout=timeout)
        value = self.meas_value()
        self.check_errors(f'{mtype} measurement on CH{ch}')
        return value

    # ---- waveform record ------------------------------------------------------------------------------------------------
    def waveform(self, ch):
        """(times, volts) of the displayed record. Times are relative to the trigger point: t = XZEro + n * XINcr (p. 2-217 / 2-218);
        volts = (dl - YOFf) * YMUlt + YZEro (p. 2-219). ASCII, one byte per point (DATa pp. 2-69 to 2-74)."""
        for cmd in (f'DATa:SOUrce CH{ch}', 'DATa:ENCdg ASCIi', 'DATa:WIDth 1', 'DATa:STARt 1', 'DATa:STOP 2500'):
            self.write(cmd)
        xinc = _last_number(self.query('WFMPre:XINcr?'))
        xzero = _last_number(self.query('WFMPre:XZEro?'))
        ymult = _last_number(self.query('WFMPre:YMUlt?'))
        yoff = _last_number(self.query('WFMPre:YOFf?'))
        yzero = _last_number(self.query('WFMPre:YZEro?'))
        raw = self.query('CURVe?').strip()
        if raw.upper().startswith('CURVE'):
            raw = raw[5:]
        try:
            dl = [float(x) for x in raw.replace(';', ',').split(',') if x.strip()]
        except ValueError:
            raise InstrumentError(f'Unreadable waveform data from CURVe?: {raw[:60]!r}')
        if len(dl) < 100 or xinc <= 0 or ymult == 0:
            raise InstrumentError(f'Waveform record not usable (points {len(dl)}, XINcr {xinc:g}, YMUlt {ymult:g})')
        times = [xzero + i * xinc for i in range(len(dl))]
        volts = [(d - yoff) * ymult + yzero for d in dl]
        self.check_errors(f'waveform CH{ch}')
        return times, volts

    def waveform_burst(self, ch, count, half_points=1250):
        """`count` successive records of CH<ch>, each only the window of 2*half_points points around the middle of the 2500-point record
        (the trigger point), for repeatability checks. The scale preamble and the source are read ONCE and errors are checked once at the end;
        only CURVe? is repeated. Times are relative to the window centre (t = (n - half_points) * XINcr), so they do not depend on how
        XZEro is reported for a partial record. Returns [(times, volts), ...]."""
        half = max(60, min(1250, int(half_points)))
        start, stop = 1251 - half, 1250 + half
        for cmd in (f'DATa:SOUrce CH{ch}', 'DATa:ENCdg ASCIi', 'DATa:WIDth 1', f'DATa:STARt {start}', f'DATa:STOP {stop}'):
            self.write(cmd)
        xinc = _last_number(self.query('WFMPre:XINcr?'))
        ymult = _last_number(self.query('WFMPre:YMUlt?'))
        yoff = _last_number(self.query('WFMPre:YOFf?'))
        yzero = _last_number(self.query('WFMPre:YZEro?'))
        if xinc <= 0 or ymult == 0:
            raise InstrumentError(f'Waveform scale not usable (XINcr {xinc:g}, YMUlt {ymult:g})')
        out = []
        for _ in range(count):
            raw = self.query('CURVe?').strip()
            if raw.upper().startswith('CURVE'):
                raw = raw[5:]
            try:
                dl = [float(x) for x in raw.replace(';', ',').split(',') if x.strip()]
            except ValueError:
                raise InstrumentError(f'Unreadable waveform data from CURVe?: {raw[:60]!r}')
            if len(dl) < 2 * half * 0.9:
                raise InstrumentError(f'Waveform window not usable ({len(dl)} points, expected {2 * half})')
            out.append(([(i - half) * xinc for i in range(len(dl))], [(d - yoff) * ymult + yzero for d in dl]))
        self.check_errors(f'waveform CH{ch}')
        return out
