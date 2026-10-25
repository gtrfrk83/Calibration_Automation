"""Software stand-in for the 3 Series MDO (MDO32 / MDO34) on the MDO bench: the same signal model as the MDO4000C simulator (simulated_mdo.SimMdo,
linked to the simulated 5560A, 96270A, generator and meters), answering the 3 Series command texts of drivers/tektronix_mdo3.py.

make_mdo3_bench(model='34-1000') returns (bench, transports) for mdo4000c_verification.IO(...) configured for the MDO3 family.  What the simulator
does NOT model (so a pass here proves the wire sequence, not the instrument): the real *IDN? / *OPT? reply forms (invented here in the form the
manual describes), the bandwidth read-back after FULl, the RF behaviour without 3-SA3, the trigger counter settling time.  A command a 2-channel
MDO32 cannot take (CH3 / CH4) sets a command error in the event status register, as a real instrument would report it (assumed).
"""
from __future__ import annotations

import re

from .simulated import SimBench, SimFlukeTransport
from .simulated_mdo import MdoState, SimGen, SimMdo, SimMeter, SimRF


class Mdo3State(MdoState):
    def reset(self):
        super().reset()
        self.trigfreq = False
        self.dvm = dict(mode='DC', src=1)
        self.afg.update(load='FIFTY')
        self.esr = 0
        self.events = []


class SimMdo3(SimMdo):
    def __init__(self, bench, model='34-1000'):
        super().__init__(bench)
        self.model_key = model
        self.channels = int(model[1])
        self.bw_hz = float(model.split('-')[1]) * 1e6

    def _error(self, code, text):
        self.s.esr |= 32
        self.s.events.append(f'{code},"{text}"')
        return None

    def _meas(self, slot):
        m = self.s.meas.get(slot, {})
        if m.get('type') == 'BURST':
            return 3.0e-11
        return super()._meas(slot)

    def _input_freq(self):
        f = self.bench.fluke
        if f['operate'] and f['scope'] == 'LEVSINE':
            return f['freq']
        return self.bench.gen['f'] if self.bench.gen.get('on') else None

    def handle(self, cmd):
        s = self.s
        u = cmd.upper().strip()
        if u == '*IDN?':
            return f'TEKTRONIX,MDO{self.model_key[:2]},SIM0003,CF:91.1CT FV:v1.0'
        if u == '*OPT?':
            return 'SA3:Spectrum analyzer 3 GHz,AFG:Arbitrary Function Generator,DVM:Digital Voltmeter'
        if u == '*ESR?':
            esr, s.esr = s.esr, 0
            return str(esr)
        if u == 'EVMSG?':
            return s.events.pop(0) if s.events else '0,"No events; Queue empty"'
        m = re.match(r'(?:SELECT:CH|CH|TRIGGER:A:LEVEL:CH|DVM:SOURCE CH)(\d)', u)
        if m and int(m.group(1)) > self.channels:
            return self._error(-113, 'Undefined header') if not u.endswith('?') else '0'
        m = re.match(r'CH(\d):(TERMINATION|BANDWIDTH|SCALE|OFFSET|POSITION|COUPLING)(\?| (.*))$', u)
        if m:
            ch = s.ch[int(m.group(1))]
            key, query, val = m.group(2), m.group(3) == '?', (m.group(4) or '').strip()
            if key == 'COUPLING':
                return None
            if key == 'BANDWIDTH':
                if query:
                    return f"{(self.bw_hz if ch['bw'] == 'FUL' else ch['bw']):.4E}"
                ch['bw'] = 'FUL' if val.startswith('FUL') else float(val)
                return None
            if key == 'TERMINATION':
                if query:
                    return f"{ch['term']:.1E}"
                ch['term'] = {'FIFTY': 50.0, 'MEG': 1e6}.get(val, None) or float(val)
                self.bench.mdo['term'] = '1M' if ch['term'] > 1e3 else '50'
                return None
            k = {'SCALE': 'scale', 'OFFSET': 'offset', 'POSITION': 'pos'}[key]
            if query:
                return f'{ch[k]:.6E}'
            ch[k] = float(val)
            return None
        if re.match(r'TRIGGER:A:LEVEL:CH\d ', u):
            return None
        if u == 'DISPLAY:TRIGFREQUENCY ON':
            s.trigfreq = True; return None
        if u == 'DISPLAY:TRIGFREQUENCY?':
            return '1' if s.trigfreq else '0'
        if u == 'TRIGGER:FREQUENCY?':
            fr = self._input_freq()
            return f'{fr * 1.0000001:.12E}' if (s.trigfreq and fr) else '99.10E+36'
        if u == 'DIAG:SELECT ALL':
            return None
        if u in ('DIAG:STATE?', 'DIAG:SELECT:ALL'):
            return self._error(-113, 'Undefined header')          # no query form / no such function on the 3 Series (pp. 2-262)
        if u == 'DVM:MODE?':
            return {'DC': 'DC', 'ACR': 'ACRMS', 'FRE': 'FREQUENCY'}.get(s.dvm['mode'], s.dvm['mode'])
        if u == 'DVM:SOURCE?':
            return f"CH{s.dvm['src']}"
        if u.startswith('DVM:DISPLAYSTYLE'):
            return None
        if u == 'AFG:OUTPUT:LOAD:IMPEDANCE FIFTY':
            s.afg['load'] = 'FIFTY'; return None
        if u == 'AFG:OUTPUT:LOAD:IMPEDANCE?':
            return s.afg['load']
        m = re.match(r'AFG:(FUNCTION|FREQUENCY|AMPLITUDE|OFFSET)\?$', u)
        if m:
            a = s.afg
            return {'FUNCTION': a['fn'], 'FREQUENCY': f"{a['freq']:.12E}", 'AMPLITUDE': f"{a['vpp']:.6E}", 'OFFSET': f"{a['off']:.6E}"}[m.group(1)]
        if u == 'RF:REFLEVEL?':
            return f"{s.rf['ref'] if s.rf['ref'] is not None else 0.0:.6E}"
        if u == 'MEASUREMENT:GATING NONE':
            return self._error(-224, 'Illegal parameter value')    # p. 2-388: {OFF|SCREen|CURSor}
        if u.startswith('DATA:ENCDG ') and not u.startswith('DATA:ENCDG ASCI'):
            return None
        return super().handle(cmd)


def make_mdo3_bench(model='34-1000', gen_model='33250A'):
    """(bench, transports) for IO(addrs, transports=...): scope (3 Series model key, e.g. '34-1000' or '32-200'), cal, rf1, rf2, gen, dmm, counter."""
    bench = SimBench()
    bench.mdo_state = Mdo3State()
    bench.mdo = {'term': '1M'}
    t = dict(scope=SimMdo3(bench, model), cal=SimFlukeTransport(bench), rf1=SimRF(bench, 'rf1'), rf2=SimRF(bench, 'rf2'), gen=SimGen(bench, gen_model),
             dmm=SimMeter(bench), counter=SimMeter(bench))
    return bench, t
