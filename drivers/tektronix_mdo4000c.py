"""Tektronix MDO4000C mixed-domain oscilloscope over USB (USBTMC / VISA).

Command strings follow the MDO4000/B/C Series Programmer Manual. Writes are never retried; every setting that matters is read
back and compared, and the instrument's event queue is checked after each group of settings (check_errors) so a rejected command
stops the run instead of producing a reading for the wrong setup.

The RF (spectrum) commands are collected in RF below so they can be corrected in one place if a firmware revision words them
differently; the spectrum is read as a waveform (RF_NORMal / RF_AVErage) and analysed in software, not through marker commands.
"""
from __future__ import annotations

import math
import time

from .base import Instrument, InstrumentError
from .transport import SerialSettings

# ---- the spectrum-analyser command set, in one place ---------------------------------------------------------------------------
RF = dict(
    on='SELect:RF_NORMal ON',
    avg_on='SELect:RF_AVErage ON',
    normal_off='SELect:RF_NORMal OFF',
    center='RF:FREQuency {v:.9g}',
    span='RF:SPAN {v:.9g}',
    start='RF:STARt {v:.9g}',
    stop='RF:STOP {v:.9g}',
    rbw_manual='RF:RBW:MODe MANual',
    rbw_auto='RF:RBW:MODe AUTO',
    rbw='RF:RBW {v:.9g}',
    rbw_q='RF:RBW?',
    ref_level='RF:REFLevel {v:.9g}',
    avg_count='ACQuire:NUMAVg {n:d}',
    detect_avg='RF:DETECTIONMethod:RF_AVErage:MODe MANual',
    detect_avg_set='RF:DETECTIONMethod:RF_AVErage:MANual AVErage',
)

COUPLING_OK = ('DC',)


class TektronixMDO4000C(Instrument):
    MODEL = 'Tektronix MDO4000C'
    IDN_MATCH = ('MDO4',)
    DEFAULT_TIMEOUT = 30.0
    SERIAL = None            # USB / LAN / GPIB only

    # ---- connection -------------------------------------------------------------------------------------------------
    def connect(self):
        self.open(verify_model=True)
        self.write('*CLS')
        self.write('HEADer OFF')
        self.write('VERBose OFF')
        self.idn = self.identify()
        self.model = self._model_from_idn(self.idn)
        return self

    @staticmethod
    def _model_from_idn(idn):
        for part in idn.replace(' ', '').split(','):
            if part.upper().startswith('MDO4'):
                return part.upper().replace('MDO', '')          # '4104C'
        return ''

    def installed_options(self):
        """Tokens from *OPT? (e.g. SA3, SA6, AFG, DVM) for pre-selecting the option boxes; the technician can override."""
        try:
            raw = self.query('*OPT?').upper()
        except Exception:
            return set()
        tokens = set()
        for key in ('SA3', 'SA6', 'AFG', 'DVM'):
            if key in raw:
                tokens.add(key)
        return tokens

    def opc(self, timeout=None):
        old = None
        if timeout:
            old = self.t.set_timeout(timeout)
        try:
            self.query('*OPC?')
        finally:
            if timeout:
                self.t.set_timeout(self.DEFAULT_TIMEOUT)

    def check_errors(self, context=''):
        """Raise if the event status register reports a command / execution / device error since the last check."""
        esr = int(float(self.query('*ESR?').strip()))
        if esr & 0b00111100:       # CME, EXE, DDE, QYE
            try:
                detail = self.query('EVMsg?').strip()
            except Exception:
                detail = ''
            raise InstrumentError(f'The oscilloscope rejected a command{" (" + context + ")" if context else ""}: ESR={esr} {detail}')

    def cleanup(self):
        try:
            self.write('AFG:OUTPut:STATe OFF')
        except Exception:
            pass

    # ---- helpers ----------------------------------------------------------------------------------------------------
    def set_verified(self, cmd_set, cmd_query, value, rel=1e-3, abs_=1e-9):
        """Write a numeric setting, read it back, compare. Never retried."""
        self.write(f'{cmd_set} {value:.9g}')
        got = float(self.query(cmd_query).strip().split()[-1])
        if not math.isclose(got, value, rel_tol=rel, abs_tol=abs_):
            raise InstrumentError(f'{cmd_set}: set {value:g}, instrument reports {got:g}')
        return got

    def set_enum_verified(self, cmd_set, cmd_query, value):
        self.write(f'{cmd_set} {value}')
        got = self.query(cmd_query).strip().upper()
        if not got.startswith(value.upper()[:3]):
            raise InstrumentError(f'{cmd_set}: set {value}, instrument reports {got}')

    # ---- default state ----------------------------------------------------------------------------------------------
    def default_setup(self):
        self.write('FACtory')
        self.opc(60)
        self.write('HEADer OFF')
        self.write('VERBose OFF')

    # ---- analog channel ---------------------------------------------------------------------------------------------
    def select_only(self, ch):
        for n in (1, 2, 3, 4):
            self.write(f'SELect:CH{n} {"ON" if n == ch else "OFF"}')

    def channel(self, ch, term=None, bw=None, vscale=None, offset=None, position=0.0):
        """Termination ('50' / '1M'), bandwidth (TWEnty / TWOFifty / FULl), scale, offset, position; each read back."""
        if term:
            ohms = {'50': 50.0, '1M': 1.0e6}[term]
            self.set_verified(f'CH{ch}:TERmination', f'CH{ch}:TERmination?', ohms, rel=1e-2)
        if bw:
            self.set_enum_verified(f'CH{ch}:BANdwidth', f'CH{ch}:BANdwidth?', bw)
        self.write(f'CH{ch}:COUPling DC')
        if vscale is not None:
            self.set_verified(f'CH{ch}:SCAle', f'CH{ch}:SCAle?', vscale, rel=1e-3)
        if position is not None:
            self.set_verified(f'CH{ch}:POSition', f'CH{ch}:POSition?', position, abs_=1e-6)
        if offset is not None:
            self.set_verified(f'CH{ch}:OFFSet', f'CH{ch}:OFFSet?', offset, rel=1e-4, abs_=1e-6)

    # ---- acquisition / horizontal / trigger ------------------------------------------------------------------------
    def acquire_mode(self, mode, averages=16):
        self.write(f'ACQuire:MODe {mode}')
        if mode.upper().startswith('AVE'):
            self.write(f'ACQuire:NUMAVg {averages}')
        self.write('ACQuire:STOPAfter RUNSTop')
        self.write('ACQuire:STATE RUN')

    def timebase(self, seconds_per_div):
        self.set_verified('HORizontal:SCAle', 'HORizontal:SCAle?', seconds_per_div, rel=1e-3)

    def delay(self, seconds):
        self.write('HORizontal:DELay:MODe ON')
        self.write(f'HORizontal:DELay:TIMe {seconds:.12g}')

    def trigger_line(self):
        self.write('TRIGger:A:TYPe EDGe')
        self.write('TRIGger:A:EDGE:SOUrce LINE')
        self.write('TRIGger:A:MODe AUTO')

    def trigger_edge(self, source, level=None, slope='RISe', mode='AUTO'):
        self.write('TRIGger:A:TYPe EDGe')
        self.write(f'TRIGger:A:EDGE:SOUrce {source}')
        self.write(f'TRIGger:A:EDGE:SLOpe {slope}')
        self.write(f'TRIGger:A:MODe {mode}')
        if level is not None:
            self.write(f'TRIGger:A:LEVel {level:.9g}')

    # ---- measurements -------------------------------------------------------------------------------------------------
    def measure_setup(self, mtype, source, slot=1, source2=None):
        n = f'MEASUrement:MEAS{slot}'
        self.write(f'{n}:STATE OFF')
        self.write(f'{n}:TYPe {mtype}')
        self.write(f'{n}:SOUrce1 {source}')
        if source2:
            self.write(f'{n}:SOUrce2 {source2}')
        self.write(f'{n}:STATE ON')

    def stats_reset(self, weighting=None):
        self.write('MEASUrement:STATIstics:MODe OFF')
        if weighting:
            self.write(f'MEASUrement:STATIstics:WEIghting {weighting}')
        self.write('MEASUrement:STATIstics:MODe ALL')

    def _num(self, cmd):
        v = float(self.query(cmd).strip().split()[-1])
        if not math.isfinite(v) or abs(v) > 1e36:
            raise InstrumentError(f'Invalid reading from {cmd}: {v}')
        return v

    def stat_mean(self, slot=1):
        return self._num(f'MEASUrement:MEAS{slot}:MEAN?')

    def stat_stddev(self, slot=1):
        return self._num(f'MEASUrement:MEAS{slot}:STDdev?')

    def meas_value(self, slot=1):
        return self._num(f'MEASUrement:MEAS{slot}:VALue?')

    def mean_of(self, ch, averages=16, wait=3.0):
        """Mean of a channel with N-point acquisition averaging (the manual's DC tests)."""
        self.measure_setup('MEAN', f'CH{ch}')
        self.acquire_mode('AVErage', averages)
        self.stats_reset(weighting=16)
        time.sleep(wait)
        return self.stat_mean()

    def delay_stddev(self, ch, samples=100, wait=8.0):
        """Delay (falling edge to falling edge, last occurrence) statistics: returns the standard deviation."""
        n = 'MEASUrement:MEAS1'
        self.write(f'{n}:STATE OFF')
        self.write(f'{n}:TYPe DELay')
        self.write(f'{n}:SOUrce1 CH{ch}')
        self.write(f'{n}:SOUrce2 CH{ch}')
        self.write(f'{n}:DELay:EDGE1 FALL')
        self.write(f'{n}:DELay:EDGE2 FALL')
        self.write(f'{n}:DELay:DIRection BACKWards')
        self.write(f'{n}:STATE ON')
        self.stats_reset(weighting=samples)
        time.sleep(wait)
        return self.stat_stddev()

    # ---- waveform transfer ---------------------------------------------------------------------------------------------
    def fetch(self, source):
        """(x_values, y_values) of a waveform source, scaled by WFMOutpre. ASCII encoding keeps the transport simple."""
        self.write(f'DATa:SOUrce {source}')
        self.write('DATa:ENCdg ASCIi')
        self.write('DATa:STARt 1')
        self.write('DATa:STOP 1000000')
        npts = int(float(self.query('WFMOutpre:NR_Pt?').strip()))
        self.write(f'DATa:STOP {npts}')
        xin = float(self.query('WFMOutpre:XINcr?')); xz = float(self.query('WFMOutpre:XZEro?'))
        ym = float(self.query('WFMOutpre:YMUlt?')); yo = float(self.query('WFMOutpre:YOFf?')); yz = float(self.query('WFMOutpre:YZEro?'))
        po = float(self.query('WFMOutpre:PT_Off?'))
        raw = [float(s) for s in self.query('CURVe?').strip().split(',') if s.strip()]
        xs = [xz + (i - po) * xin for i in range(len(raw))]
        return xs, [yz + ym * (r - yo) for r in raw]

    def edge_time(self, ch, level=None):
        """Time (s, relative to the horizontal reference) of the first rising 50 % crossing in the acquired record."""
        self.write('ACQuire:STATE RUN')
        time.sleep(1.0)
        self.write('ACQuire:STATE STOP')
        xs, ys = self.fetch(f'CH{ch}')
        lo, hi = min(ys), max(ys)
        mid = (lo + hi) / 2 if level is None else level
        for i in range(1, len(ys)):
            if ys[i - 1] < mid <= ys[i]:
                return xs[i - 1] + (mid - ys[i - 1]) / (ys[i] - ys[i - 1]) * (xs[i] - xs[i - 1])
        raise InstrumentError('No rising edge found in the acquired record; check the time-mark signal and trigger.')

    # ---- digital channels -------------------------------------------------------------------------------------------------
    def digital_on(self):
        for d in range(16):
            self.write(f'SELect:D{d} ON')

    def digital_threshold(self, d, volts):
        self.set_verified(f'D{d}:THReshold', f'D{d}:THReshold?', volts, rel=1e-3, abs_=1e-3)

    def digital_state(self, d, settle=3.0):
        """'high', 'low' or 'toggling' for digital channel D<d> after a settle time."""
        time.sleep(settle)
        self.write('ACQuire:STATE RUN')
        time.sleep(0.5)
        self.write('ACQuire:STATE STOP')
        _xs, ys = self.fetch(f'D{d}')
        if all(y > 0.5 for y in ys): return 'high'
        if all(y <= 0.5 for y in ys): return 'low'
        return 'toggling'

    # ---- RF / spectrum -------------------------------------------------------------------------------------------------------
    def rf_cmd(self, key, **fmt):
        self.write(RF[key].format(**fmt))

    def rf_setup(self, center=None, span=None, start=None, stop=None, rbw=None, ref_level=None, averages=None, average_trace=True):
        """Turn on the RF channel and set the frequency window; the event queue is checked afterwards."""
        self.select_only(0)                    # all analog channels off (the RF tests use the RF input only)
        self.rf_cmd('on')
        if average_trace:
            self.rf_cmd('avg_on'); self.rf_cmd('normal_off')
        if averages:
            self.rf_cmd('avg_count', n=averages)
        if start is not None: self.rf_cmd('start', v=start)
        if stop is not None: self.rf_cmd('stop', v=stop)
        if center is not None: self.rf_cmd('center', v=center)
        if span is not None: self.rf_cmd('span', v=span)
        if ref_level is not None: self.rf_cmd('ref_level', v=ref_level)
        if rbw is not None:
            self.rf_cmd('rbw_manual'); self.rf_cmd('rbw', v=rbw)
        self.check_errors('RF setup')

    def rf_rbw(self):
        return self._num(RF['rbw_q'])

    def rf_trace(self, average=True):
        """(frequencies Hz, levels dBm) of the spectrum trace currently on screen."""
        xs, ys = self.fetch('RF_AVErage' if average else 'RF_NORMal')
        return xs, ys

    def rf_settle(self, seconds):
        time.sleep(seconds)

    # ---- AFG / DVM ----------------------------------------------------------------------------------------------------------------
    def afg_set(self, function, frequency=None, vpp=None, offset=None):
        self.write(f'AFG:FUNCtion {function}')
        if frequency is not None: self.write(f'AFG:FREQuency {frequency:.9g}')
        if vpp is not None: self.write(f'AFG:AMPLitude {vpp:.9g}')
        if offset is not None: self.write(f'AFG:OFFSet {offset:.9g}')
        self.write('AFG:OUTPut:LOAd:IMPedance FIFty')
        self.write('AFG:OUTPut:STATe ON')
        self.check_errors('AFG setup')

    def afg_off(self):
        self.write('AFG:OUTPut:STATe OFF')

    def dvm(self, mode, ch):
        self.write('DVM:MODe ' + mode)
        self.write(f'DVM:SOUrce CH{ch}')
        self.write('DVM:DISplaystyle MINIMum')
        self.check_errors('DVM setup')

    def dvm_value(self, settle=3.0):
        time.sleep(settle)
        return self._num('DVM:MEASUrement:VALue?')

    def dvm_frequency(self, settle=3.0):
        time.sleep(settle)
        return self._num('DVM:MEASUrement:FREQuency?')

    # ---- self test / signal-path compensation ---------------------------------------------------------------------------------
    def run_diagnostics(self, timeout=900):
        """Run the full self test and return (passed, log text)."""
        self.write('DIAg:SELect:ALL')
        self.write('DIAg:LOOP:OPTion ONCE')
        self.write('DIAg:STATE EXECute')
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(5)
            state = self.query('DIAg:STATE?').strip().upper()
            if not state.startswith(('EXE', 'RUN')):
                break
        flag = self.query('DIAg:RESUlt:FLAg?').strip().upper()
        log = self.query('DIAg:RESUlt:LOG?').strip()
        return flag.startswith('PASS'), log

    def run_spc(self, timeout=1200):
        """Signal path compensation; returns (passed, status)."""
        self.write('CALibrate:INTERNal:STARt')
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(10)
            st = self.query('CALibrate:INTERNal:STATus?').strip().upper()
            if 'RUN' not in st and 'PROG' not in st:
                break
        result = self.query('CALibrate:RESults:SPC?').strip().upper()
        return result.startswith('PASS'), result
