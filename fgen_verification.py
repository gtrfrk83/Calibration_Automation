"""Keysight / Agilent 33210A, 33220A and 33250A function generator performance verification, driven from the manufacturer's tables.

Test points and limits are NOT written in this file: they are loaded from specs/keysight_<model>_pv.json, written by
specs/build_fgen_spec.py from Chapter 4 (Calibration Procedures) of each model's Service Guide. Default limits: 1 year.

Instruments
  Generator under test     USB / GPIB / LAN (RS-232 on the 33250A)            drivers/keysight_332xx.py
  Fluke 5790B              AC amplitude and low-frequency flatness (the manual uses a 3458A DMM here)   drivers/fluke_5790b.py
  Frequency counter        internal timebase (53131A Opt 010 in the manual)   drivers.ReferenceMeter; leave blank to type readings
  Power meter + sensor     0 / +10 / +20 dB range flatness (E4418B + 8482A, -20 dB attenuator for +20 dB)   drivers.ReferenceMeter;
                           leave blank to type readings
Flatness follows the manual's worksheet: offset_N = 10 log(5 V100k^2) - 10 log(5 V1k^2) from the 5790B readings, and each
point is (P(f) - P(100 kHz)) + offset_N, which is what the power meter shows in Relative Power mode with that offset entered.
The generator output is switched OFF after every point and before every wiring change; each switch is confirmed with OUTP?.
Hardware I/O is off in demo mode, and demo results are labelled as demo data everywhere.

    import fgen_verification
    fgen_verification.main('33220A')       # what Procedures/Keysight_33220A_Verification.py does
"""
import json, math, sys, threading, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))  # ui_theme, report and drivers sit next to the Manager
import ui_port
import ui_theme as ui                   # only its toolkit-free helpers here (si_row, si_one, report_filename, Settings); the window code is in fgen_view_tk.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import appdata
import datamode
import procmods_engine
import reset_startup
import surprise
import virtualbench
import drivers

MODEL = SPEC_PATH = SPEC = POINTS = None
PERIODS = {'90 days': '90d', '1 year': '1y'}
PERIOD_LABEL = {v: k for k, v in PERIODS.items()}
KINDS = ('SELFTEST', 'TIMEBASE', 'ACAMP', 'LFFLAT', 'FLAT')
REF_CMC_PATH = HERE / 'specs' / 'fgen_332xx_reference_cmc.json'
STD_INPUTS = {'INPUT 1 (type N)': 'INPUT1', 'INPUT 2 (binding posts)': 'INPUT2'}
FLAT_REF_HZ = 100e3
STD_MODEL = '5790B'        # the standards sheet (specs/standards) of the measuring standard: its AC voltage specification is the budget for AC amplitude / low-frequency flatness
WBND_REF_HZ = 1e3          # wideband flatness is measured relative to 1 kHz (5790B manual pp. 4-31, 4-32)
COUNTER_REFS = {'External 10 MHz (GPS)': 'EXT', 'Internal timebase': 'INT'}
FLAT_METHODS = {'WBND': '5790B wideband input (relative to 1 kHz)', 'POWER': 'Power meter (manual method)'}
SETTLE = {'TIMEBASE': 2.0, 'ACAMP': 1.0, 'LFFLAT': 1.0, 'FLAT': 1.5}


class SpecError(ValueError):
    pass


class NeedReference(RuntimeError):
    """A flatness point was asked for before the AC amplitude / low-frequency references it needs were recorded."""


# ================================================================================================================
# spec
# ================================================================================================================
def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if spec.get('schema') != 4:
        raise SpecError(f'{Path(path).name}: expected a schema 4 (function generator) spec')
    periods = spec['periods']
    if spec['default_period'] not in periods:
        raise SpecError('default_period is not one of periods')
    for s in spec['sections']:
        for i, p in enumerate(s['points'], 1):
            where = f"{s['id']} point {i}"
            if p['kind'] not in KINDS:
                raise SpecError(f'{where}: unknown kind {p["kind"]!r}')
            if set(p['limits']) != set(periods) or any(not v > 0 for v in p['limits'].values()):
                raise SpecError(f'{where}: limits must be positive for every period {periods}')
            if p['kind'] != 'SELFTEST' and not (p.get('frequency') and p.get('amp_unit') and p.get('load')):
                raise SpecError(f'{where}: needs frequency, amp_unit and load')
    return spec


def flatten(spec):
    points = []
    for s in spec['sections']:
        for raw in s['points']:
            p = dict(raw)
            p['id'] = len(points) + 1
            p['section'] = s['id']; p['section_title'] = s['title']; p['page'] = s['page']
            p['group'] = s['group']; p['setup'] = s['setup']
            p.setdefault('quick', False)
            p['desc'] = describe(p)
            points.append(p)
    return points


def _si(value, unit):
    n, sym = ui.si_one(value, unit)
    return f'{n} {sym}'


def describe(p):
    """Display text only; the point keeps base units."""
    k = p['kind']
    if k == 'SELFTEST':
        return 'Complete self-test (*TST?)'
    func = 'Sine' if p['function'] == 'SIN' else 'Square'
    load = 'High Z' if p['load'] == 'INF' else '50 ohm'
    if p['amp_unit'] == 'DBM':
        amp = f"{p['amplitude']:+.2f} dBm"
    elif p['amp_unit'] == 'VPP':
        amp = f"{p['amplitude']:.2f} Vpp"
    else:
        amp = _si(p['amplitude'], 'V') + 'rms'
    text = f"{func} {amp} @ {_si(p['frequency'], 'Hz')}, {load}"
    if k == 'FLAT':
        text += f", {p['range_db']:+d} dB range".replace('+0 dB', '0 dB')
    return text


def configure(model):
    global MODEL, SPEC_PATH, SPEC, POINTS
    MODEL = model
    SPEC_PATH = HERE / 'specs' / f'keysight_{model.lower()}_pv.json'
    SPEC = load_spec(SPEC_PATH)
    POINTS = flatten(SPEC)
    apply_period(POINTS, SPEC['default_period'])


def apply_period(points, period):
    for p in points:
        p['error'] = float(f"{p['limits'][period]:.9g}")


def judge(p, reading):
    if p['kind'] == 'SELFTEST':
        return 'PASS' if reading == 0 else 'FAIL'
    return 'PASS' if abs(reading - p['nominal']) <= p['error'] else 'FAIL'


def point_group(p, method):
    """Wiring group: wideband flatness uses one connection (5790B WIDEBAND) for all three ranges, no attenuator."""
    return 'WBND' if p['kind'] == 'FLAT' and method == 'WBND' else p['group']


def setup_text(p, method):
    if p['kind'] == 'FLAT' and method == 'WBND':
        return ('Generator OUTPUT to the 5790B WIDEBAND input (50 ohm) with a 3 ft RG-58 cable and an N(m)-BNC(f) adapter. Output setup 50 ohm. '
                'Flatness = 20 log(V(f) / V(1 kHz)) at the same setting, 5790B range locked (5790B manual pp. 4-31, 4-32).')
    return p['setup']


def flat_offset(results, range_db):
    """Worksheet step 5 (100kHz_NdB_offset) in dB from the recorded 5790B readings, or raise NeedReference."""
    hi, lo = f'100k_{range_db}dB', f'1k_{range_db}dB'
    found = {}
    for p in POINTS:
        if p.get('ref') in (hi, lo):
            rec = results.get(str(p['id']))
            if rec is not None and rec.get('reading') is not None:
                found[p['ref']] = rec['reading']
    if hi not in found or lo not in found:
        names = [f'{q["section_title"]} {q["desc"]}' for q in POINTS if q.get('ref') in (hi, lo)]
        raise NeedReference(f'The {range_db} dB range offset needs these points first: ' + '; '.join(names))
    v100, v1 = found[hi], found[lo]
    return 10 * math.log10(5.0 * v100 ** 2) - 10 * math.log10(5.0 * v1 ** 2)


def to_visa(text):
    """'COM9' / '9' -> 'ASRL9::INSTR'; anything that already looks like a VISA resource passes through."""
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port (COM9) or a full VISA address (USB0::...::INSTR, GPIB0::10::INSTR).')
    return f'ASRL{int(t)}::INSTR'


# ================================================================================================================
# bench I/O (no tkinter: the simulated-bench tests drive this class directly)
# ================================================================================================================
class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """The generator under test, the 5790B, and (optionally) a counter and a power meter. A reference left without an
    address is read by the technician: ask_number(prompt, unit) is called and must return a float (or None to stop)."""

    def __init__(self, addrs, transports=None, ask_number=None, std_input='INPUT1', flat_method='POWER', counter_ref='EXT', mods=None, virtual=False,
                 surprise_handler=None):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        self.ask_number = ask_number
        self.std_input = std_input
        if flat_method not in SPEC.get('flatness_methods', ['POWER']):
            raise ValueError(f'{MODEL}: flatness method {flat_method} is not available (spec allows {SPEC.get("flatness_methods")})')
        self.flat_method = flat_method
        self.wideband = None
        self.counter_ref = counter_ref
        self.uut = self.std = self.counter = self.power = None
        t = transports or {}

        def tr(key, **kw):
            return t[key] if key in t else drivers.open_visa(to_visa(addrs[key]), timeout=30, **kw)

        try:
            self.uut = getattr(drivers, f'Keysight{MODEL}')(tr('uut', **self._serial(addrs, 'uut')), self.log, label=MODEL)
            self.uut.connect()
            self.std = drivers.Fluke5790B(tr('std', **self._serial(addrs, 'std')), self.log, label='5790B')
            self.std.connect()
            if 'counter' in t or (addrs.get('counter') or '').strip():
                self.counter = self._connect_counter(tr)
            if 'power' in t or (addrs.get('power') or '').strip():
                self.power = drivers.ReferenceMeter(tr('power'), self.log, label='PowerMeter'); self.power.connect()
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.uut.idn
        self.guards = []
        if surprise_handler is not None:
            self.enable_surprise(surprise_handler)

    # replies that must be numbers (the first field of a comma list counts), per registry key; every other reply is only checked for empty / a prompt character
    _EXPECT = {'selftest': 'float', 'load.query': 'float', 'offs.query': 'float', 'freq.query': 'float', 'volt.query': 'float',       # generator under test
               'meas.query': 'float', 'range.query': 'float', 'extrig.query': 'float',                                               # 5790B
               'read': 'float', 'imp.query': 'float', 'gate.query': 'float', 'exp.query': 'float', 'rosc.freq.query': 'float',        # counter
               'freq.meas': 'float', 'power.meas': 'float'}                                                                          # generic counter / power meter

    def enable_surprise(self, handler, force=False):
        """Stop on surprise (surprise.py, opt-in; wired here at the engine level, no driver edited).  handler(Surprise) -> True = Continue; it must have
        been made on the Tk thread (surprise.tk_handler).  On every instrument (generator, 5790B, counter, power meter) a reply that is empty / a prompt
        character / not a number where a number is expected, or a query that times out twice, is a Stop-only surprise.  The generator's OUTP? is left to
        the driver (an output state it cannot confirm stays a SafetyError / InstrumentError, never a dialog).  A setting whose read-back does not match, and
        an error-queue entry after a setting, are routed through surprise.checked (see _checked): Stop only, except one case.  No write is ever repeated.
        A virtual (demo) command log is left alone unless force=True (tests), so the simulated bench never prompts."""
        self.guards = [g for g in (surprise.attach_guard(o, handler, force, expect=self._EXPECT, stop_only=True, skip=('outp.query',) if o is self.uut else ())
                                   for o in (self.uut, self.std, self.counter, self.power) if o is not None) if g]
        return self.guards

    def _checked(self, inst, call, *args, errq_continue=False, readback='the value that was set', **kw):
        """A driver call that sets something, reads it back and compares, then reads the error queue (all inside the one driver method).  With no guard it
        is exactly `call(*args)`.  With one, a failure after an exchange with the instrument is the surprise it was: the read-back that did not match
        (Stop only: the driver call stopped part-way, the rest of the settings were never sent) or the error-queue entry (Stop only, or Stop / Continue
        when errq_continue: the queue check is the last thing the driver method does, so Continue leaves it exactly as if the queue had been empty).  A failure
        before anything was sent (a range check) and a +2009 'no external timebase' (the counter's own, expected, diagnosis) keep the driver's message."""
        def how(_exc, command, reply):
            if not command or reply.lstrip().lstrip('+').startswith('2009'):
                return None
            if 'ERR?' in command.upper():
                return dict(kind='errqueue', expected='empty error queue', stop_only=not errq_continue)
            return dict(kind='readback', expected=readback, stop_only=True)
        return surprise.checked(inst, call, *args, classify=how, **kw)

    def reset_roles(self):
        return [d for d in (self.std, self.counter, self.power) if d is not None], [self.uut]

    def pm_drivers(self):
        return tuple(d for d in (self.uut, self.std, self.counter, self.power) if d is not None)

    def _connect_counter(self, tr):
        """A 53131A / 53132A gets its own driver (input, gate and reference set and read back); any other counter is used
        through the generic ReferenceMeter (MEASure:FREQuency?), with its input set up by the technician."""
        try:
            return drivers.Keysight5313x(tr('counter'), self.log, label='Counter').connect()
        except drivers.InstrumentError as exc:
            if 'Expected' not in str(exc):
                raise
        meter = drivers.ReferenceMeter(tr('counter'), self.log, label='Counter'); meter.connect()
        return meter

    @staticmethod
    def _serial(addrs, key):
        """Serial settings only for ASRL (RS-232) addresses; the 5790B needs XON/XOFF and CR LF."""
        a = (addrs.get(key) or '').strip().upper()
        if not (a.startswith(('ASRL', 'COM')) or a.isdigit()):
            return {}
        if key == 'std':
            s = drivers.FLUKE_5790B_SERIAL
            return dict(baud=int(addrs.get('std_baud') or s.baud), data_bits=s.data_bits, parity=s.parity, stop_bits=s.stop_bits,
                        write_termination=s.write_termination, read_termination=s.read_termination, flow_control=s.flow_control)
        # 33250A RS-232 (User's Guide ch. 2): factory 57600 baud, 8 data bits, no parity; set its handshake to None (the factory DTR/DSR
        # is not offered by the transport). Line endings are not verified on hardware - prefer GPIB.
        return dict(baud=int(addrs.get('uut_baud') or 57600), write_termination='\n', read_termination='\n')

    # ---- safety ----------------------------------------------------------------------------------------------
    def all_off(self):
        """Generator output OFF (confirmed). Called after every point and before every wiring prompt."""
        if self.uut:
            self.uut.output(False)

    def close(self):
        for obj in (self.uut, self.std, self.counter, self.power):
            if obj is None:
                continue
            try: obj.cleanup()
            except Exception: pass
            try: obj.close()
            except Exception: pass
        self.save_log()

    def save_log(self):
        if virtualbench.log_is_virtual(self.log): return          # a virtual (demo) session is never evidence
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {MODEL} session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass

    # ---- readings --------------------------------------------------------------------------------------------
    def _manual(self, prompt, unit):
        if self.ask_number is None:
            raise drivers.InstrumentError(f'No address for this reference and no way to type a reading: {prompt}')
        v = self.ask_number(prompt, unit)
        if v is None:
            raise drivers.InstrumentError('Reading not entered; run stopped.')
        return float(v)

    def _frequency(self, expected_hz):
        """Returns (Hz, raw). A 53131A / 53132A is set to channel 1, 50 ohm, AC coupled, 1 s gate, expected frequency."""
        ext = self.counter_ref == 'EXT'
        if self.counter is None:
            where = 'on its external 10 MHz (GPS) reference' if ext else 'on its internal timebase'
            return (self._manual(f'Read the frequency counter {where} (generator: 10 MHz sine, 1 Vpp).', 'Hz'),
                    dict(counter='typed', reference=('EXT (operator)' if ext else 'INT (operator)')))
        raw = dict(reference='not checked (generic counter)')
        if isinstance(self.counter, drivers.Keysight5313x):
            ref_hz = self._checked(self.counter, self.counter.set_reference, self.counter_ref)          # EXT: selected, checked now, and re-checked every reading
            gate_s = self.pm_param('fgen.counter_gate', 1.0)
            self._checked(self.counter, self.counter.configure_frequency, channel=1, gate_s=gate_s, impedance=50, coupling='AC', expected_hz=expected_hz)
            src, auto = self.counter.reference()
            if src != self.counter_ref:
                raise drivers.InstrumentError(f'Counter timebase is {src}, expected {self.counter_ref}.')
            raw = dict(counter=self.counter.idn.split(',')[1].strip(), gate_s=gate_s,
                       reference=f'EXT {ref_hz / 1e6:g} MHz (checked)' if ext else 'INT')
        f = self.counter.frequency()
        if not 1e6 < f < 1e8:
            raise drivers.InstrumentError(f'Counter reads {f:g} Hz: check the cable and the counter input (50 ohm, channel 1).')
        return f, raw

    def _power(self, what):
        if self.power:
            try:
                return self.power.power()
            except surprise.SurpriseStop:
                raise
            except drivers.InstrumentError as exc:
                raise drivers.InstrumentError(f'{exc} - check the sensor, attenuator and cable, and that the power meter is zeroed.') from exc
        return self._manual(f'Read the power meter in dBm ({what}). Relative mode and offset OFF: type the absolute reading.', 'dBm')

    def _out(self, p, frequency=None):
        self._checked(self.uut, self.uut.setup, p['function'], frequency or p['frequency'], p['amplitude'], p['amp_unit'], p['load'])    # the output is enabled next: Stop only
        self._checked(self.uut, self.uut.output, True, readback='OUTP? = 1')         # OUTP? is not guarded; an unconfirmed ON is a Stop-only surprise, an unconfirmed OFF stays a SafetyError
        time.sleep(virtualbench.scaled(self._settle(p), self.virtual))

    def _settle(self, p):
        if p.get('settle_s') is not None: return p['settle_s']           # a per-point modification (procmods)
        k = p['kind']
        return self.pm_param(f'fgen.settle.{k.lower()}', SETTLE[k]) if k in SETTLE else self.pm_param('fgen.settle.other', 1.0)

    # ---- one point -----------------------------------------------------------------------------------------
    @procmods_engine.point_commands()
    def measure(self, p, results, pref_cache):
        """Returns (reading, raw dict). The generator output is OFF when this returns or raises."""
        try:
            return self._measure(p, results, pref_cache)
        finally:
            self.all_off()

    def _measure(self, p, results, pref_cache):
        k = p['kind']
        if k == 'SELFTEST':
            passed, detail = self._checked(self.uut, self.uut.self_test)
            return (0 if passed else 1), dict(detail=detail)
        if k == 'TIMEBASE':
            self._out(p)
            return self._frequency(p['frequency'])
        if k in ('ACAMP', 'LFFLAT'):
            self._checked(self.std, self.std.select_input, self.std_input)
            self._checked(self.std, self.std.set_external_trigger, True, errq_continue=True)       # the queue check is its last step
            self._checked(self.std, self.std.set_range_for, p['nominal'])
            self._out(p)
            return self._std_volts(p['frequency']), {}
        if k == 'FLAT' and self.flat_method == 'WBND':
            return self._flat_wideband(p, pref_cache)
        if k == 'FLAT':
            offset = flat_offset(results, p['range_db'])
            key = p['section']
            if key not in pref_cache:
                self._out(p, FLAT_REF_HZ)
                pref = self._power(f'{p["section_title"]} reference, 100 kHz')
                self.uut.output(False)
                expected = p['amplitude'] - (20.0 if p['range_db'] == 20 else 0.0)
                if p['range_db'] == 20 and pref > 10.0:
                    raise drivers.SafetyError(f'The power meter reads {pref:+.2f} dBm at +23.9 dBm output: the -20 dB attenuator is '
                                              'not fitted. Output switched OFF. Fit the attenuator before continuing.')
                if abs(pref - expected) > 3.0:
                    raise drivers.InstrumentError(f'Power meter reads {pref:+.2f} dBm, expected about {expected:+.1f} dBm: check the sensor, '
                                                  'attenuator and cable, and that the power meter is zeroed.')
                pref_cache[key] = pref
            pref = pref_cache[key]
            self._out(p)
            pf = self._power(f'{p["desc"]}')
            return (pf - pref) + offset, dict(method='POWER', p_ref_dbm=pref, p_dbm=pf, offset_db=offset)
        raise drivers.InstrumentError(f'No executor for {k}')

    def _std_volts(self, expected_hz, where=''):
        where = where or ('the WIDEBAND input' if self.std.last_input == 'WBND' else self.std.last_input)
        try:
            volts, freq = self.std.measure()
        except surprise.SurpriseStop:
            raise                                       # the operator's Stop (the dialog already said what and where), not a message to extend
        except drivers.InstrumentError as exc:
            raise drivers.InstrumentError(f'{exc} - check the cable to the 5790B {where}.') from exc
        if not math.isclose(freq, expected_hz, rel_tol=0.01):
            raise drivers.InstrumentError(f'5790B measured {freq:g} Hz, expected {expected_hz:g} Hz: check the cable to the 5790B {where}.')
        return volts

    def _flat_wideband(self, p, ref_cache):
        """Flatness on the 5790B WIDEBAND input (50 ohm), relative to 1 kHz at the same setting and on the same locked range:
        20 log10(V(f) / V(1 kHz)). The 1 kHz reading is taken at the start of each section in every run."""
        if self.wideband is None:
            self.wideband = self.std.require_wideband(max(q['frequency'] for q in POINTS if q['kind'] == 'FLAT'))
        expected = math.sqrt(10 ** (p['amplitude'] / 10) * 1e-3 * 50.0)      # dBm into 50 ohm -> V rms
        if expected > 7.0:
            raise drivers.SafetyError(f'{p["amplitude"]:+.2f} dBm is {expected:.2f} V rms, above the 5790B wideband 7 V range.')
        self._checked(self.std, self.std.select_input, 'WBND')
        self._checked(self.std, self.std.set_external_trigger, True, errq_continue=True)
        rng = self._checked(self.std, self.std.set_range_for, expected)
        key = p['section']
        if key not in ref_cache:
            self._out(p, WBND_REF_HZ)
            v1k = self._std_volts(WBND_REF_HZ)
            self.uut.output(False)
            if abs(v1k / expected - 1) > 0.2:
                raise drivers.InstrumentError(f'5790B wideband reads {v1k:.4g} V at 1 kHz, expected about {expected:.4g} V '
                                              f'({p["amplitude"]:+.2f} dBm into 50 ohm): check the cable to the WIDEBAND input and the output setup.')
            ref_cache[key] = v1k
        v1k = ref_cache[key]
        self._out(p)
        vf = self._std_volts(p['frequency'])
        return 20 * math.log10(vf / v1k), dict(method='WBND', v_1k=v1k, v_f=vf, std_range_v=rng)


def demo_reading(p):
    """Deterministic synthetic reading, labelled as demo data everywhere it appears."""
    if p['kind'] == 'SELFTEST':
        return 0, {}
    return p['nominal'] + p['error'] * math.sin(p['id'] * 1.71) * 0.38, {}


# ================================================================================================================
# uncertainty and report rows
# ================================================================================================================
def _ref_cmc():
    try:
        return json.loads(REF_CMC_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def measure_budget(p, sc=None):
    """uncertainty_budget.Budget of a sine-wave AC amplitude / low-frequency flatness point read on the Fluke 5790B (the measuring standard of this
    procedure): the 5790B's published 'Voltage, AC [Sinewave, Absolute]' accuracy at the voltage and frequency / its coverage divisor (99 %: 2.576), + its
    resolution when the sheet has one, k = 2, checked against the laboratory's AC Voltage - Measure CMC.  None when the point is not a sine wave
    (the 5790B sinewave rows do not describe a square wave), the scope or the 5790B sheet is missing, or no 5790B row covers the point: those
    stay CMC-only."""
    if p['kind'] not in ('ACAMP', 'LFFLAT') or p.get('function') != 'SIN':
        return None
    try:
        import report_pdf, uncertainty_budget
        sc = sc or report_pdf.scope()
        if sc is None:
            return None
        b = uncertainty_budget.build('ACV', p['nominal'], 'V', standard=STD_MODEL, frequency=p['frequency'], scope=sc, direction='input', basis='measure')
    except Exception:
        return None
    return b if b.hit is not None and b.cmc is not None else None


def uncertainty_value(p):
    """(value, unit, source) behind point_uncertainty: the unrounded uncertainty in `unit`, or (None, None, '') when there is none.
    Sine-wave AC amplitude / low-frequency flatness: the larger of the 5790B budget and the scope's AC Voltage - Measure CMC (source 'budget');
    the time base, square-wave points and any point without a 5790B row: the scope CMC alone (source 'scope')."""
    scope_value, scope_unit, scope_src = None, None, 'scope'
    if p['kind'] in ('ACAMP', 'LFFLAT', 'TIMEBASE'):
        import report_pdf
        sc = report_pdf.scope()
        if sc is not None:
            kind = 'FREQ' if p['kind'] == 'TIMEBASE' else 'ACV'
            scope_value = sc.dmm(kind, p['nominal'], None, None if kind == 'FREQ' else p['frequency'], basis='measure')
            scope_unit = 'Hz' if kind == 'FREQ' else 'V'
            b = measure_budget(p, sc) if scope_value is not None else None
            if b is not None:
                scope_value, scope_src = max(scope_value, b.value), 'budget'
    entry = _ref_cmc().get(p['kind']) or {}
    if entry.get('rel') is not None or entry.get('abs') is not None:
        value = (entry.get('rel') or 0) * abs(p['nominal'] if p['kind'] != 'FLAT' else 1.0) + (entry.get('abs') or 0)
        unit = entry.get('unit', p['unit'])
        if scope_value is not None and unit == scope_unit and value < scope_value:
            value = scope_value          # an editable reference value may never be reported below the A2LA scope (or the budget)
        return value, unit, 'reference file'
    if scope_value is not None:
        return scope_value, scope_unit, scope_src
    return None, None, ''


def point_uncertainty(p):
    """(text, source) - the editable reference file first, then the laboratory scope (Measure entries), else ''."""
    import uncertainty
    value, unit, source = uncertainty_value(p)
    if value is None:
        return '', ''
    return uncertainty.format_value(value, unit), source


def tar_tur_fields(p, r=None):
    """dict(TAR, TUR) strings for one point, used only when the report asks for them.
    TUR = tolerance / the uncertainty printed in the Uncertainty column (same numeric value, rounded up as printed), only when the
    tolerance and the uncertainty are in the same unit; blank for the self test, '(typical)' points (a typical value is not a limit)
    and points with no printed uncertainty.  TAR only for AC amplitude and low-frequency flatness, which are read on the Fluke 5790B
    (the only reference this program uses for them), sine waves only: the 5790B specmanager row at that voltage and frequency, in volts.  The time base
    (counter) and RF flatness (power meter / relative 5790B wideband, in dB) have no matching specification row: TAR blank."""
    import tartur
    try:
        if p['kind'] == 'SELFTEST' or p.get('typical'):
            return dict(TAR='', TUR='')
        import uncertainty
        value, unit, _src = uncertainty_value(p)
        u = uu = None
        if value is not None:
            u, uu = uncertainty.round_up(value), unit
        acc = au = None
        if p['kind'] in ('ACAMP', 'LFFLAT') and p.get('function') == 'SIN':        # the 5790B sinewave rows do not describe a square wave
            acc, au = tartur.standard_accuracy('5790B', 'ACV', p['nominal'], frequency=p['frequency'], direction='input')
        return tartur.ratio_fields(tartur.from_values(tartur.half_width(p['nominal'] - p['error'], p['nominal'] + p['error']), p['unit'], acc, au, u, uu))
    except Exception:
        return dict(TAR='', TUR='')


def display_ref(p):
    """SI-prefix reference for display: dB is never prefixed (no 'mdB'); volts and hertz scale with the nominal."""
    return 1.0 if p['unit'] == 'dB' else (p['nominal'] or p['error'])


def _db_row(p, r, failed, sec, unc):
    lo, hi = p['nominal'] - p['error'], p['nominal'] + p['error']
    dp = max(len(f'{p["error"]:g}'.split('.')[1]) if '.' in f'{p["error"]:g}' else 0, 2)
    return {'Section': sec, 'Description': p['desc'], 'Nominal': f'{p["nominal"]:.{dp}f} dB', 'Tolerance -': f'{lo:.{dp}f}',
            'Tolerance +': f'{hi:.{dp}f}', 'UOM': 'dB', 'As Found': f'{r["reading"]:.{dp + 2}f}', 'OOT': 'OOT' if failed else '',
            'As Left': 'Same', 'Uncertainty': unc}


def certificate_row(p, r):
    """The report row of one recorded point (r = its record), or None."""
    import report_pdf
    failed = r['result'] == 'FAIL'
    sec = p['section_title']
    if p['kind'] == 'SELFTEST':
        return {'Section': sec, 'Description': p['desc'], 'Nominal': 'Pass', 'Tolerance -': 'N/A', 'Tolerance +': 'N/A', 'UOM': '',
                'As Found': 'Pass' if r['reading'] == 0 else 'Fail', 'OOT': 'OOT' if failed else '', 'As Left': 'Same', 'Uncertainty': ''}
    unc, _src = point_uncertainty(p)
    if p['unit'] == 'dB':
        return _db_row(p, r, failed, sec, unc)
    desc = p['desc'] + (' (typical)' if p.get('typical') else '')
    if p['kind'] == 'TIMEBASE' and r.get('raw', {}).get('reference'):
        desc += f"; counter timebase {r['raw']['reference']}"
    return report_pdf.cert_row(desc, p['nominal'], p['nominal'] - p['error'], p['nominal'] + p['error'], p['unit'],
                               r['reading'], failed, section=sec, uncertainty=unc)


def certificate_rows(results):
    """Rows for one result set (As Found only); the window builds As Found + As Left rows with App.certificate_rows."""
    rows = []
    for p in POINTS:
        r = results.get(str(p['id']))
        if r:
            rows.append(certificate_row(p, r))
    return rows


# ================================================================================================================
# application
# ================================================================================================================
class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    WIRING = {
        'NONE': ('Self-test', [('Disconnect', 'Remove any cable from the generator OUTPUT. No connections are needed for the self-test.')]),
        'COUNTER': ('Connect the frequency counter', [('Connect', 'Generator OUTPUT to the frequency counter channel 1 input with a 50 ohm BNC cable.'),
                                                      ('Counter', '53131A / 53132A: the program sets channel 1 to 50 ohm, AC, 1 s gate. Any other '
                                                                  'counter: terminate its input at 50 ohm (manual step 1).'),
                                                      ('Reference', 'External timebase (default): the 10 MHz GPS reference on the counter\'s '
                                                                    'rear-panel Ref In. A 53131A / 53132A is switched to EXT and the reference is '
                                                                    'checked before and during the reading (the manual asks for 0.1 ppm).')]),
        'STD': ('Connect the Fluke 5790B', [('Connect', 'Generator OUTPUT to the 5790B {input} with a short RG-58 BNC cable '
                                                        '(type N input: N(m) to BNC(f) adapter; binding posts: BNC to dual banana).'),
                                            ('5790B', 'No other cables on the 5790B inputs. Guard and ground as your lab practice.')]),
        'POWER': ('Connect the power sensor', [('Power meter', 'Zero and calibrate the power meter with the sensor, then connect the sensor.'),
                                               ('Connect', 'Generator OUTPUT to the power sensor (N(m) to BNC(f) adapter), no attenuator.')]),
        'WBND': ('Connect the 5790B WIDEBAND input', [('Connect', 'Generator OUTPUT to the 5790B WIDEBAND input (type N, 50 ohm) with a 3 ft '
                                                                 'RG-58 cable and an N(m) to BNC(f) adapter. No attenuator.'),
                                                      ('5790B', 'Nothing connected to INPUT 1 / INPUT 2. The program selects the WIDEBAND input; '
                                                                'the 50 MHz cable correction (/AF option) must be off.')]),
        'POWER_ATT': ('Fit the -20 dB attenuator', [('Attenuator', 'Fit the -20 dB attenuator (8491A Opt 020 or equivalent) between the generator '
                                                                   'OUTPUT and the power sensor.'),
                                                    ('Why', 'The +20 dB range points output +23.9 dBm (about 245 mW), above the 8482A sensor maximum.')]),
    }

    def __init__(self, root, model, demo=False, fast_demo=False):
        configure(model)
        self.init_virtual(demo, fast_demo)
        self.root = root; self.demo = demo; self.io = None; self._busy = False; self.stop = False
        self.results = {}; self.pref_cache = {}; self.conditions_ok = False
        self.pm_init('fgen', MODEL, demo=demo, lists=[POINTS])         # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings(f'fgen_{MODEL}')
        g = self.settings.get
        self.asset = port.var(); self.serial = port.var()
        self.addr = {k: port.var(g(k, d)) for k, d in (('uut', 'USB0::0x0957::0x0407::MY00000000::INSTR'), ('std', 'GPIB0::8::INSTR'),
                                                                   ('counter', ''), ('power', ''), ('std_baud', '9600'), ('uut_baud', '57600'))}
        self.std_input = port.var(g('std_input', 'INPUT 1 (type N)'))
        cr = g('counter_ref', 'External 10 MHz (GPS)')
        self.counter_ref = port.var(cr if cr in COUNTER_REFS else 'External 10 MHz (GPS)')
        methods = SPEC.get('flatness_methods', ['POWER'])
        saved = g('flat_method', FLAT_METHODS[methods[0]])
        self.flat_method = port.var(saved if saved in [FLAT_METHODS[m] for m in methods] else FLAT_METHODS[methods[0]])
        self.period = port.var(g('period', PERIOD_LABEL[SPEC['default_period']]))
        self.test_set = port.var('Full verification')
        self.status = port.var()
        self.detail = port.var('Select a test point to see its limits and setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self._build_ui()
        self.on_period(save=False)
        self.status.set(virtualbench.status_text(self) if demo else
                        'Step 1: enter the Instrument ID. Step 2: enter the addresses and press Test Connections. Step 3: Run All.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)

    # ------------------------------------------------------------------ selection
    def active(self, p):
        if p.get('skip'): return False                               # a point skipped by a procedure modification
        return not (self.test_set.get().startswith('Quick') and not p['quick'])

    def active_points(self): return [p for p in POINTS if self.active(p)]

    @property
    def busy(self): return self._busy

    @busy.setter
    def busy(self, value):
        self._busy = value
        if hasattr(self, 'btn_run'): self.ui_view.sync_buttons(self)

    # ------------------------------------------------------------------ layout
    VIEW = 'fgen_view'                          # the toolkit's window code: fgen_view_tk (Tk), later _qt

    @property
    def ui_view(self): return port.view(self.VIEW)

    def _build_ui(self): self.ui_view.build_ui(self)

    # ------------------------------------------------------------------ table
    def _visible(self, p):
        if not self.active(p): return False
        res = self.results.get(str(p['id']), {}).get('result', '')
        sec = self.show_section.get(); st = self.show_status.get()
        if sec != 'All sections' and p['section_title'] != sec: return False
        if st == 'Not tested' and res: return False
        if st == 'Passed' and res != 'PASS': return False
        if st == 'Failed (OOT)' and res != 'FAIL': return False
        if not self.status_visible(str(p['id']), st): return False
        return True

    def _row(self, p):
        name = p['desc'] + (' ★' if p['quick'] else '')
        if p['kind'] == 'SELFTEST':
            key = str(p['id']); rec = self.results.get(key, {}); res = rec.get('result', '')
            word = lambda r: '' if not r or r.get('reading', '') == '' else ('Pass' if r['reading'] == 0 else 'Fail')
            f, l = self.found.get(key), self.left.get(key)
            left = word(l) or ('Same' if (self.is_left and f) else '')
            shown = {'PASS': '✔ PASS', 'FAIL': '✖ FAIL'}.get(res, '—')
            return (p['id'], name, 'Pass', '', '', '', word(f), '', left, shown), (res.lower() or 'pending',)
        cells, tags = self.shell_cells(p['id'], p['nominal'], p['nominal'] - p['error'], p['nominal'] + p['error'], p['unit'])
        return (p['id'], name, *cells), tags

    def pm_driver_classes(self): return (getattr(drivers, f'Keysight{MODEL}'), drivers.Fluke5790B, drivers.Keysight5313x, drivers.ReferenceMeter)

    def pm_point_fields(self, view):
        out = super().pm_point_fields(view)
        out['nominal']['note'] = ('The nominal is the value the reading is judged against (and the 5790B range is chosen from it). The generator '
                                  'output is set from the amplitude and frequency of the point, which this window does not change.')
        return out

    def pm_plan_point(self, p):
        """The commands IO.measure sends for point p: a dry run of that routine on the simulated bench (procmods_plan).  Readings the
        technician types (power meter, counter) are answered with the value the point expects; earlier readings the flatness offset needs are
        stood in by the nominal.  Only the commands are of interest, never the values."""
        import procmods_plan
        from drivers.simulated_fgen import make_fgen_bench

        def ask(prompt, unit):
            if unit == 'dBm':
                return p.get('amplitude', 0.0) - (20.0 if p.get('range_db') == 20 else 0.0)
            if unit == 'Hz':
                return p.get('frequency', 1e7)
            return p.get('nominal', 0.0)

        def build(mods):
            bench, t = make_fgen_bench(MODEL)
            addrs = self._addrs()
            t = {k: v for k, v in t.items() if k in ('uut', 'std') or (addrs.get(k) or '').strip()}        # a reference with no address is typed by hand
            if p['kind'] in ('ACAMP', 'LFFLAT'): bench.connected = 'std'
            elif p['kind'] == 'FLAT': bench.connected = 'wbnd' if self.method() == 'WBND' else 'power'
            else: bench.connected = 'counter'
            return IO({}, transports=t, ask_number=ask, std_input=STD_INPUTS[self.std_input.get()], flat_method=self.method(),
                      counter_ref=COUNTER_REFS[self.counter_ref.get()], mods=mods)
        stand_in = {str(q['id']): {'reading': q['nominal']} for q in POINTS if q.get('ref')}
        return procmods_plan.run_plan(self.pm_state, build, lambda io: io.measure(p, stand_in, {}))

    def pm_point_title(self, p): return f'{p.get("section_title", "")} - {p.get("desc", "")}'.strip(' -')

    def pm_standby(self):
        if self.io is not None and not self.fast_demo: self.io.all_off()

    def refresh(self):
        keep = self.ui_view.table_selection(self)
        self.ui_view.table_set_rows(self, ((str(p['id']), *self._row(p)) for p in POINTS if self._visible(p)), keep)
        self.update_summary()

    def _update_row(self, p):
        iid = str(p['id'])
        if self.ui_view.table_has(self, iid):
            values, tags = self._row(p); self.ui_view.table_update_row(self, iid, values, tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(self.active_points())
        self.update_shell_sections(self.active_points(), lambda p: p['section_title'])

    def on_period(self, save=True):
        self.pm_revert(POINTS)                                       # limits come from the period table: take the modifications off,
        apply_period(POINTS, PERIODS[self.period.get()])
        self.pm_apply(POINTS)                                        # then put them back (they only apply if they fit this period)
        for records in (self.found, self.left):      # As Found and As Left are re-judged against the newly selected limits
            for key, rec in records.items():
                rec['result'] = judge(POINTS[int(key) - 1], rec['reading'])
        if save: self._save_settings()
        self.refresh()

    def on_select(self, _event=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        lines = [p['desc']]
        if p['kind'] != 'SELFTEST':
            v, _r, u = ui.si_row([p['nominal'] - p['error'], p['nominal'] + p['error']], p['unit'], ref=display_ref(p))
            lines.append(f'Acceptable reading: {v[0]} to {v[1]} {u}  ({self.period.get()} limit)  |  Manual page {p["page"]}'
                         + ('  |  Quick check (Q)' if p['quick'] else ''))
        if p.get('typical'): lines.append('Guideline only: ' + p.get('note', ''))
        if p['kind'] in ('ACAMP', 'LFFLAT') and p['nominal'] >= 2.5:
            lines.append('5790B note: the 7 V range input is 50 kOhm (Table 4-4). With the generator\'s 50 ohm source this reads about 0.1 % '
                         'lower than a 1 MOhm DMM such as the 3458A the manual lists.')
        if p.get('ref'): lines.append(f'Worksheet reference: {p["ref"].replace("k_", "kHz_")}_reference (used for the flatness offsets).')
        lines.append('Setup: ' + setup_text(p, self.method()))
        rec = self.results.get(str(p['id']), {})
        if rec.get('raw'):
            lines.append('Recorded: ' + ', '.join(f'{k} = {v:.6g}' if isinstance(v, float) else f'{k} = {v}' for k, v in rec['raw'].items()))
        if self.found_left_text(p): lines.append(self.found_left_text(p))
        self.detail.set('\n'.join(lines))

    # ------------------------------------------------------------------ connection
    def find_instruments(self):
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        self.ui_view.set_choices(self, found)
        self.status.set(f'{len(found)} VISA resource(s) found: ' + (', '.join(found) if found else 'none') + '. Pick the address for each instrument.')

    def _addrs(self):
        return {k: v.get() for k, v in self.addr.items()}

    def test_connections(self):
        if self.fast_demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware, so there is nothing to connect.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect()
            if self.virtual:          # demo: the real IO / driver code over a simulated generator, 5790B and (when an address is given) counter / power meter
                from drivers.simulated_fgen import make_fgen_bench
                bench, t = make_fgen_bench(MODEL)
                addrs = self._addrs()
                t = {k: v for k, v in t.items() if k in ('uut', 'std') or (addrs.get(k) or '').strip()}        # a reference with no address is typed by hand, as in a real run
                self._vb = (bench, None, None)
                self.io = IO({}, transports=t, ask_number=self.ask_number_threadsafe, std_input=STD_INPUTS[self.std_input.get()],
                             flat_method=self.method(), counter_ref=COUNTER_REFS[self.counter_ref.get()], mods=self.pm_state, virtual=True)
            else:
                self.io = IO(self._addrs(), ask_number=self.ask_number_threadsafe, std_input=STD_INPUTS[self.std_input.get()],
                             flat_method=self.method(), counter_ref=COUNTER_REFS[self.counter_ref.get()], mods=self.pm_state,
                             surprise_handler=self._surprise_handler())
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True)
        if not self.demo: self._save_settings()
        extra = '\n'.join(f'{n}: {o.idn}' for n, o in (('Counter', self.io.counter), ('Power meter', self.io.power)) if o)
        manual = [n for n, o in (('frequency counter', self.io.counter), ('power meter', self.io.power)) if not o]
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: ' + self.io.ident + tag + '. Generator output is OFF.')
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'{MODEL}: {self.io.ident}\nFluke 5790B: {self.io.std.idn}\n{extra}\n'
                            + (f'You will type the readings for: {", ".join(manual)}.\n' if manual else '') + 'Generator output is OFF.' + tag)

    def _surprise_handler(self):
        """The Stop / Continue dialog for stop-on-surprise, made ON the Tk thread (here: the Test connections handler), once per window.
        None in demo (virtual or fast): the simulated bench never prompts."""
        if self.demo or self.fast_demo: return None
        if getattr(self, '_sp_handler', None) is None: self._sp_handler = port.surprise_handler(self.root)
        return self._sp_handler

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else ('Demo - no hardware' if self.demo else 'Not connected'),
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_settings(self):
        for k, v in self.addr.items(): self.settings.set(k, v.get())
        self.settings.set('std_input', self.std_input.get()); self.settings.set('period', self.period.get())
        self.settings.set('flat_method', self.flat_method.get()); self.settings.set('counter_ref', self.counter_ref.get())
        self.settings.save()

    def ask_number_threadsafe(self, prompt, unit):
        """Called from the worker thread; asks on the main thread and waits (port.call_from_worker; an exception in the dialog gives None, as before)."""
        def ask():
            if self.virtual:       # demo: the same window; the box holds a plausible simulated reading, which may be replaced
                return port.ask_number('Type the reading' + ' [DEMO]', f'{prompt}\n\nReading in {unit}:\n\nDEMO: the box holds a simulated reading from the virtual bench; type your own if you like.',
                                       parent=self.root, initial=virtualbench.fgen_typed_value(self._vb, unit))
            return port.ask_number('Type the reading', f'{prompt}\n\nReading in {unit}:', parent=self.root)
        return port.call_from_worker(self.root, ask)

    # ------------------------------------------------------------------ running
    def request_stop(self): self.stop = True; self.status.set('Stopping after current test point.')
    def run_all(self): self.execute([p for p in self.active_points() if str(p['id']) not in self.results])
    def run_section(self): self.run_shown_section()

    def rerun(self):
        sel = self.ui_view.table_selection(self)
        if sel: self.execute([POINTS[int(sel[0]) - 1]])
        else: port.message('info', 'Selection', 'Select a test point first.')

    def rerun_from(self):
        sel = self.ui_view.table_selection(self)
        if sel: self.execute(self.points_from(POINTS, sel[0]))
        else: port.message('info', 'Selection', 'Select a test point first.')

    def execute(self, points):
        if self.busy or not points: return
        if not self.asset.get().strip(): port.message('warning', 'Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        if not self.confirm_found_overwrite(points): return
        if not self.fast_demo and self.io is None: self.test_connections()
        if not self.fast_demo and self.io is None: return
        if not self.fast_demo and not self.conditions_ok and not port.operator_prompt('Test conditions', 'Before you start',
                [('Warm-up', 'The generator has been powered on for at least 1 hour (manual, Test Considerations).'),
                 ('Environment', SPEC['source']['conditions'] + '.'),
                 ('Cables', 'Short RG-58 or equivalent 50 ohm cables only.')],
                facts=[('Points to run', len(points)), ('Limits', self.period.get())], ok='Conditions met - start', parent=self.root):
            return
        self.conditions_ok = True
        self.stop = False; self.busy = True; self.pref_cache = {}
        self.reset_then(lambda: self._next(points, 0, None))     # every run (first, re-run, resume): reset to defaults before the first point

    def method(self):
        return next(k for k, v in FLAT_METHODS.items() if v == self.flat_method.get())

    def on_counter_ref(self):
        self._save_settings()
        if self.io is not None:
            self.io.counter_ref = COUNTER_REFS[self.counter_ref.get()]
        self.status.set(f'Counter timebase: {self.counter_ref.get()}.')

    def on_method(self):
        self._save_settings()
        if self.io is not None:
            self.io.flat_method = self.method()
        done = [p for p in POINTS if p['kind'] == 'FLAT' and str(p['id']) in self.results
                and self.results[str(p['id'])].get('raw', {}).get('method', 'POWER') != self.method()]      # (the set being collected)
        self.status.set(f'Flatness will be measured with: {self.flat_method.get()}.'
                        + (f' {len(done)} recorded flatness point(s) used the other method; rerun them if they should match.' if done else ''))

    def _prompt_setup(self, p):
        group = point_group(p, self.method())
        title, steps = self.WIRING[group]
        steps = [(a, b.format(input=self.std_input.get())) for a, b in steps]
        image = HERE / 'diagrams' / f'hook_332xx_{group}.png'
        facts = [('Next point', f'{p["id"]} of {len(POINTS)}'), ('Test', p['section_title']), ('Manual page', p['page'])]
        return port.operator_prompt('Rewire / verify - generator output is OFF', title,
                                [('Output OFF', f'The {MODEL} output has been switched OFF (confirmed).')] + steps,
                                facts=facts, caution='Continue only after physically checking the connections.',
                                ok='Connections verified - continue', image=str(image) if image.is_file() else None, parent=self.root)

    def _next(self, points, i, previous):
        if i >= len(points) or self.stop:
            self.busy = False; self.save()
            self.status.set('Run stopped by the operator. Progress is saved.' if self.stop else 'Run complete. Save progress or export a report.'); return
        p = points[i]
        try: p, previous = self.pm_step(points, i, previous)          # live edits: applied here, between two points (procmods_live)
        except procmods_engine.LiveApplyError as exc: self._error(exc); return
        if p is None: port.after(self.root, 30, lambda: self._next(points, i + 1, previous)); return     # skipped by an edit made during the run
        key = point_group(p, self.method())
        if not self.fast_demo and key != previous:
            try: self.io.all_off()
            except Exception as exc: self._error(exc); return
            if not self._prompt_setup(p):
                self.busy = False; self.status.set('Paused for wiring'); return
        self.status.set(f'Running {p["id"]}/{len(POINTS)}: {p["section_title"]} - {p["desc"]}')
        if self.ui_view.table_has(self, str(p['id'])): self.ui_view.table_select(self, str(p['id']), see=True)
        if self.virtual: virtualbench.fgen_operator_sets_up(self._vb, key)          # the virtual operator cables the output as the prompt said
        if self.fast_demo:
            reading, raw = demo_reading(p)
            if p['kind'] == 'FLAT': raw = dict(raw, method=self.method())
            self._record(p, reading, raw, True); port.after(self.root, 30, lambda: self._next(points, i + 1, key))
            return

        def work():
            try:
                reading, raw = self.io.measure(p, self.results, self.pref_cache)
                port.post(self.root, lambda: self._done(points, i, p, reading, raw, key))
            except Exception as exc:
                err = exc   # 'exc' is deleted when the except block ends; capture by default arg
                port.post(self.root, lambda err=err: self._error(err))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, points, i, p, reading, raw, key):
        self._record(p, reading, raw, bool(self.demo)); port.after(self.root, 30, lambda: self._next(points, i + 1, key))

    def _error(self, exc):
        self.busy = False
        title = 'SAFETY - check the front panel' if isinstance(exc, drivers.SafetyError) else 'Measurement stopped'
        self.status.set('Error - run stopped: ' + str(exc)); port.message('error', title, str(exc))

    def _record(self, p, reading, raw, synthetic):
        stale = []
        if p.get('ref'):
            rng = int(p['ref'].split('_')[1].rstrip('dB'))
            stale = [q for q in POINTS if q['kind'] == 'FLAT' and q['range_db'] == rng and str(q['id']) in self.results
                     and self.results[str(q['id'])].get('raw', {}).get('method', 'POWER') == 'POWER']
        self.results[str(p['id'])] = dict(reading=reading, result=judge(p, reading), raw=raw, synthetic=synthetic,
                                          period=PERIODS[self.period.get()], timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label,
                                          **self.pm_result_fields())
        self._update_row(p); self.save(silent=True)
        if stale:
            port.message('warning', 'Flatness reference changed',
                                   f'This reading is a flatness reference. {len(stale)} {p["ref"].split("_")[1]} range flatness result(s) were '
                                   'recorded with the earlier reference: rerun them.')

    # ------------------------------------------------------------------ files
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'{MODEL}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(model=MODEL, asset=self.asset.get(), serial=self.serial.get(), demo=self.demo,
                                        period=self.period.get(), **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if data.get('model') not in (None, MODEL):
            port.message('error', 'Checkpoint', f'This checkpoint is for a {data.get("model")}, not a {MODEL}.'); return
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'Checkpoint contains DEMO results. Load only for review (not a real calibration)?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        self.period.set(data.get('period', self.period.get())); self.load_results(data)
        self.pm_on_checkpoint(data)                                  # a saved modification snapshot is used unless the store has changed
        self.on_period(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s) restored.')

    def certificate_rows(self):
        """Report rows: As Found for every recorded point; As Left where the point was measured again after an adjustment, else 'Same'."""
        return [row for _p, row in self.certificate_pairs()]

    def certificate_pairs(self):
        """(point, report row) in the order certificate_rows() lists them."""
        pairs = []
        for p in POINTS:
            row = self.found_left_row(p, lambda r: certificate_row(p, r))
            if row: pairs.append((p, row))
        return pairs

    def export_pdf(self):
        pairs = self.certificate_pairs()
        rows = [row for _p, row in pairs]
        if not rows: port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details(f'{MODEL} performance verification', parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        used = sorted({v.get('raw', {}).get('method', 'POWER') for records in (self.found, self.left) for k, v in records.items() if POINTS[int(k) - 1]['kind'] == 'FLAT'})
        how = {'WBND': 'Flatness measured on the Fluke 5790B WIDEBAND input relative to 1 kHz (5790B Operators Manual pp. 4-31, 4-32) '
                       'instead of the manual\'s power meter method.',
               'POWER': 'Flatness measured with a power meter: 100 kHz reference plus the worksheet offset (manual method).'}
        note = ('Uncertainty: sine-wave AC amplitude and low-frequency flatness report the larger of the laboratory A2LA scope, AC Voltage - Measure, and the budget '
                'built from the published AC voltage specification of the Fluke 5790B (divided by its coverage divisor, k = 2), rounded up; square-wave amplitude uses the scope '
                'alone; the timebase uses Frequency - Measure; RF flatness uses specs/fgen_332xx_reference_cmc.json and is blank where no value is set. '
                'AC amplitude reference standard: Fluke 5790B (the manual lists a 3458A DMM). ' + ' '.join(how[m] for m in used))
        try:
            if report_pdf.details_tar_tur(details):
                rows = report_pdf.apply_tar_tur(rows, report_pdf.details_tar_tur(details), [tar_tur_fields(p) for p, _row in pairs])
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'{SPEC["manufacturer"]} {MODEL}'), ('Instrument ID', self.asset.get()),
                                                                 ('Serial', self.serial.get()), ('Limits applied', self.period.get()),
                                                                 ('Flatness method', ', '.join(FLAT_METHODS[m] for m in used) or 'not tested'),
                                                                 ('Source', f'{SPEC["source"]["document"]}, {SPEC["source"]["chapter"]}, pp. {SPEC["source"]["pages"]}')],
                                             demo=demo, details=details, footer_note=note, title='Calibration Data',
                                             snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_settings(); self.disconnect(); port.close(self.root)


def main(model, argv=None):
    argv = sys.argv if argv is None else argv
    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, model, demo=demo, fast_demo=fast)
    port.run_app(build)
