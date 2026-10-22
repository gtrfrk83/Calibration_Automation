"""Tektronix MDO4000C (MDO4024C / 4034C / 4054C / 4104C) performance verification, driven from the manufacturer's test record.

Test points and limits come from specs/tektronix_mdo4000c_pv.json (MDO4000C Series Specifications and Performance Verification,
077-1178-01 Rev B). The technician selects the model and the installed options (SA3 / SA6, AFG, DVM, digital channels, TPA-N-PRE);
only the points that apply are listed and run.

Stimulus:   Fluke 5560A (SCOPE DCV / LEVSINE / MEASR / square) for the analog tests, Fluke 96270A for the RF tests (a second RF
            source for the intermodulation test), Agilent 33220A or 33250A for the time mark and for the delta-time points the
            5560A cannot make. The AFG tests read the oscilloscope's AFG with a SCPI DMM / counter (or typed readings).
Never run unattended: the program stops and asks for every cable, terminator or instrument change, and for every
front-panel-only step. Writes are never retried; all settings are read back; outputs go to standby / off after every point.
"""
from __future__ import annotations

import csv, json, math, queue, sys, threading, time, tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import ui_theme as ui
import ui_shell
import appdata
import datamode
import drivers

SPEC_PATH = HERE / 'specs' / 'tektronix_mdo4000c_pv.json'
REF_CMC_PATH = HERE / 'specs' / 'mdo4000c_reference_cmc.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
POINTS = SPEC['points']
SECTION_TITLE = {s['id']: s['title'] for s in SPEC['sections']}
SECTION_PAGE = {s['id']: s['page'] for s in SPEC['sections']}
MODELS = SPEC['models']
PLAIN_UNITS = {'%', 'dB', 'dBm', 'dBc', 'dBm/Hz', 'dBc/Hz', 'ratio', ''}
ENBW_FACTOR = 1.0            # noise-equivalent bandwidth = ENBW_FACTOR x RBW when converting dBm to dBm/Hz (see README)
SLEEP_SCALE = 1.0            # tests set this to 0


def pause(seconds):
    if seconds > 0 and SLEEP_SCALE > 0:
        time.sleep(seconds * SLEEP_SCALE)


# ======================================================================================================================
# which points apply
# ======================================================================================================================
class Config:
    def __init__(self, model='4104C', sa='None', afg=False, dvm=False, dig=True, tpa=False):
        self.model, self.sa, self.afg, self.dvm, self.dig, self.tpa = model, sa, afg, dvm, dig, tpa

    def as_dict(self):
        return dict(model=self.model, sa=self.sa, afg=self.afg, dvm=self.dvm, dig=self.dig, tpa=self.tpa)

    def applies(self, p):
        if p.get('models') and self.model not in p['models']:
            return False
        for token in p.get('req') or []:
            ok = {'SA': self.sa in ('SA3', 'SA6'), 'SA6': self.sa == 'SA6', 'noSA': self.sa == 'None', 'AFG': self.afg, 'DVM': self.dvm,
                  'DIG': self.dig, 'TPA': self.tpa, 'noTPA': not self.tpa}[token]
            if not ok:
                return False
        return True


# ======================================================================================================================
# spectrum analysis (pure functions)
# ======================================================================================================================
def trace_peak(xs, ys, f0=None, half=None):
    best = None
    for x, y in zip(xs, ys):
        if f0 is not None and abs(x - f0) > half:
            continue
        if best is None or y > best[1]:
            best = (x, y)
    if best is None:
        raise ValueError('no spectrum points in the requested window')
    return best


def noise_floor_max(xs, ys, window=15):
    """Highest point of the running median: the noise threshold with narrow spurs ignored (the manual: 'ignoring any spurs')."""
    n = len(ys)
    if n < window:
        window = max(1, n | 1)
    half = window // 2
    best = None
    for i in range(half, n - half):
        med = sorted(ys[i - half:i + half + 1])[half]
        if best is None or med > best[1]:
            best = (xs[i], med)
    return best


def to_per_hz(level_dbm, rbw_hz):
    return level_dbm - 10 * math.log10(rbw_hz * ENBW_FACTOR)


def max_excluding(xs, ys, exclusions, half):
    best = None
    for x, y in zip(xs, ys):
        if any(abs(x - e) <= half for e in exclusions):
            continue
        if best is None or y > best[1]:
            best = (x, y)
    return best


# ======================================================================================================================
# helpers shared by the executors
# ======================================================================================================================
class Stopped(Exception):
    """The technician cancelled a prompt or pressed Stop."""


class Skip(Exception):
    """The point cannot be made with the configured instruments (reason shown to the technician)."""


def judge(p, reading):
    if p.get('passfail'):
        return 'PASS' if reading >= 0.5 else 'FAIL'
    r = float(f'{reading:.9g}')
    lo, hi = p['low'], p['high']
    if lo is not None and r < float(f'{lo:.9g}'): return 'FAIL'
    if hi is not None and r > float(f'{hi:.9g}'): return 'FAIL'
    return 'PASS'


def fmt_plain(v, sig=4):
    if v is None:
        return 'N/A'
    return f'{v:.{sig}g}'


def display_row(p, reading=None):
    """(nominal, low, high, reading, unit) display strings. SI units share a prefix; dB, %, ratio stay plain."""
    unit = p['unit']
    lo, hi, nom = p['low'], p['high'], p['nominal']
    if p.get('passfail'):
        return ('Pass', 'Pass', 'Pass', '' if reading is None else ('Pass' if reading >= 0.5 else 'Fail'), '')
    if unit in PLAIN_UNITS:
        r = '' if reading is None else fmt_plain(reading, 5)
        if unit == 'ratio' and p['kind'] == 'BW':
            return ('1.000', fmt_plain(lo), 'N/A', r, 'Vbw/Vin')
        return (fmt_plain(nom), fmt_plain(lo), fmt_plain(hi), r, unit)
    nums = [nom] + [x for x in (lo, hi) if x is not None]
    vals, reads, unit_text = ui.si_row(nums, unit, [] if reading is None else [reading])
    it = iter(vals[1:])
    lo_t = next(it) if lo is not None else 'N/A'
    hi_t = next(it) if hi is not None else 'N/A'
    return (vals[0], lo_t, hi_t, reads[0] if reads else '', unit_text)


def demo_reading(p):
    """Deterministic synthetic reading, labelled as demo data everywhere it appears."""
    s = math.sin(p['id'] * 1.713)
    lo, hi, nom = p['low'], p['high'], p['nominal']
    if p.get('passfail'):
        return 1.0
    if lo is not None and hi is not None:
        return (lo + hi) / 2 + 0.38 * (hi - lo) / 2 * s
    if hi is not None:
        return hi - (6.0 if p['unit'] in ('dBm', 'dBc', 'dBm/Hz', 'dBc/Hz') else 0.35 * abs(hi) * (1 + 0.3 * s))
    return lo + 0.3 * abs(lo) * (1 + 0.3 * s)


# ======================================================================================================================
# uncertainty
# ======================================================================================================================
_REF = {}


def reference_cmc():
    if 'v' not in _REF:
        try:
            _REF['v'] = json.loads(REF_CMC_PATH.read_text(encoding='utf-8'))
        except Exception:
            _REF['v'] = {}
    return _REF['v']


def uncertainty_text(p, raw):
    """Expanded uncertainty for a point, or 'N/A'. Points with no stimulus are always N/A; stimulus points use the lab's A2LA scope
    (5560A) or the editable reference table for the 96270A / function generator / reference meters; blank entries are N/A."""
    if p['stim'] == 'none' or p.get('passfail'):
        return 'N/A'
    import report_pdf, uncertainty
    sc = report_pdf.scope()
    k = p['kind']
    try:
        if sc is not None:
            if k == 'IMP':
                v, u, _ = sc.oscilloscope('impedance', ohms=p['nominal'])
                return uncertainty.format_value(v, 'ohm') if v is not None else 'N/A'
            if k == 'GAIN':
                ua = [abs(sc.oscilloscope('dcv', volts=abs(p[n]), impedance=p['term'])[0] or 0) / 100 * abs(p[n]) for n in ('vneg', 'vpos')]
                if all(ua):
                    return uncertainty.format_value(100 * math.hypot(*ua) / abs(p['vdiff']), '%')
            if k == 'OFFSET':
                v, u, _ = sc.oscilloscope('offset', volts=abs(p['offset']), impedance=p['term'])
                return uncertainty.format_value(v, 'V') if v is not None else 'N/A'
            if k == 'BW':
                v, u, _ = sc.oscilloscope('bandwidth', volts_pp=p['vin_pp'], frequency=p['freq'])
                if v is not None:
                    ratio = 10 ** (v / 20) - 1
                    return f'{uncertainty.round_up(ratio * max(raw.get("gain", raw.get("reading", 1)), 0.707)):.2g}'
            if k == 'DVMDC':
                v, u, _ = sc.oscilloscope('dcv', volts=abs(p['nominal']), impedance='1M')
                if v is not None:
                    return uncertainty.format_value(v / 100 * abs(p['nominal']) if u == '%' else v, 'V')
    except Exception:
        return 'N/A'
    ref = reference_cmc().get(k)
    if ref and (ref.get('rel') is not None or ref.get('abs') is not None):
        reading = abs(raw.get('reading', p['nominal']))
        value = (ref.get('rel') or 0) * reading + (ref.get('abs') or 0)
        if k == 'DVMFREQ' and sc is not None and ref.get('unit', p['unit']) == 'Hz':
            floor = sc.dmm('FREQ', p['nominal'], None, None, basis='measure')     # never below the A2LA frequency CMC
            if floor is not None and value < floor:
                value = floor
        return f'{uncertainty.round_up(value):.2g} {ref.get("unit", p["unit"])}'.strip()
    return 'N/A'


# ======================================================================================================================
# bench I/O
# ======================================================================================================================
class IO:
    """Every instrument the procedure can use. Only the oscilloscope and the 5560A are required; the others are opened when an address is given."""

    def __init__(self, addrs, transports=None):
        self.log = drivers.CommandLog()
        self.addrs = addrs
        self.scope = self.cal = self.rf1 = self.rf2 = self.gen = self.dmm = self.counter = self.power = None
        t = transports or {}
        self._tr = t
        def tr(name, **kw):
            return t[name] if name in t else drivers.open_visa(to_visa(addrs[name]), timeout=30, **kw)
        try:
            self.scope = drivers.TektronixMDO4000C(tr('scope'), self.log, label='MDO4000C'); self.scope.connect()
            self.cal = drivers.Fluke5560A(tr('cal', baud=int(addrs.get('cal_baud', 9600))), self.log, label='5560A')
            self.cal.open(verify_model=True); self.cal.clear_status()
            for key, cls, label in (('rf1', drivers.Fluke96270A, '96270A'), ('rf2', drivers.Fluke96270A, 'RF2'), ('gen', drivers.AgilentAFG, 'FuncGen'),
                                    ('dmm', drivers.ReferenceMeter, 'RefDMM'), ('counter', drivers.ReferenceMeter, 'Counter'), ('power', drivers.ReferenceMeter, 'PowerMeter')):
                if key in t or addrs.get(key, '').strip():
                    inst = cls(tr(key), self.log, label=label); inst.connect(); setattr(self, key, inst)
        except Exception:
            self.close(); raise
        self.ident = self.scope.idn

    def reconnect_scope(self, attempts=36, wait=5.0):
        """Re-open the oscilloscope after the power cycle the self test requires."""
        self.scope.close()
        for _ in range(attempts):
            try:
                t = self._tr['scope'] if 'scope' in self._tr else drivers.open_visa(to_visa(self.addrs['scope']), timeout=30)
                self.scope = drivers.TektronixMDO4000C(t, self.log, label='MDO4000C'); self.scope.connect()
                return True
            except Exception:
                pause(wait)
        return False

    def all_outputs_off(self):
        try: self.cal.standby_quiet()
        except Exception: pass
        for inst in (self.rf1, self.rf2):
            if inst:
                try: inst.output(False)
                except Exception: pass
        if self.gen:
            try: self.gen.output(False)
            except Exception: pass
        if self.scope:
            try: self.scope.afg_off()
            except Exception: pass

    def close(self):
        self.all_outputs_off()
        for inst in (self.scope, self.cal, self.rf1, self.rf2, self.gen, self.dmm, self.counter, self.power):
            if inst:
                try: inst.close()
                except Exception: pass
        self.save_log()

    def save_log(self):
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  MDO4000C session\n' + '\n'.join(self.log.lines()) + '\n')
        except OSError:
            pass


def to_visa(text):
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port (COM9) or a full VISA address (USB0::...::INSTR, GPIB0::22::INSTR).')
    return f'ASRL{int(t)}::INSTR'


# stimulus capability table (edit here if your 5560A scope option differs): leveled sine from the 5560A
SOURCE_5560A = dict(f_min=50e3, f_max=1.1e9, vpp_max=5.5)


# ======================================================================================================================
# the runner: executes one point at a time on a worker thread; every dialog goes through ask() to the main thread
# ======================================================================================================================
class Runner:
    def __init__(self, app):
        self.app = app
        self.io = app.io
        self.cfg = app.cfg
        self._wired = None
        self._scope_ctx = None
        self.skipped = {}

    # ---- plumbing --------------------------------------------------------------------------------------------------
    def check(self):
        if self.app.stop:
            raise Stopped()

    def ask(self, title, heading, steps, facts=None, caution=None, ok='Continue'):
        self.check()
        if not self.app.request('ask', dict(title=title, heading=heading, steps=steps, facts=facts, caution=caution, ok=ok)):
            raise Stopped()

    def manual(self, prompt, unit, p):
        v = self.app.request('manual', dict(prompt=prompt, unit=unit, p=p))
        if v is None:
            raise Stopped()
        return v

    def status(self, text):
        self.app.post('status', text)

    def wire(self, key, title, steps, facts=None, caution=None):
        """Prompt only when the physical setup changes."""
        if key == self._wired:
            return
        self.io.all_outputs_off()
        self.ask(title, title, steps, facts, caution, ok='Connected - continue')
        self._wired = key

    def fresh_scope(self, key):
        """Default setup once per (section, channel) group; later points only change scale, bandwidth, etc."""
        if self._scope_ctx != key:
            self.io.scope.default_setup()
            self._scope_ctx = key

    def settle_cal(self, seconds=2.0):
        pause(seconds)

    # ---- top-level dispatch -----------------------------------------------------------------------------------------------
    def run_point(self, p):
        fn = getattr(self, 'do_' + p['kind'].lower(), None)
        if fn is None:
            raise Skip(f'no executor for {p["kind"]}')
        try:
            return fn(p)
        finally:
            self.io.all_outputs_off()

    # ---- self test ----------------------------------------------------------------------------------------------------------------
    def do_selftest(self, p):
        self.wire(('SELF',), 'Self test', [('Disconnect', 'Disconnect everything from the oscilloscope inputs.'),
                  ('Warm up', 'The oscilloscope must have been running continuously for at least 20 minutes.')])
        self.status('Running system diagnostics (several minutes) ...')
        ok, log = self.io.scope.run_diagnostics()
        self.ask('Cycle power', 'Cycle the oscilloscope power', [('Power', 'The manual requires the power to be cycled after the diagnostics. Switch the oscilloscope OFF, wait 10 seconds, switch it ON and wait for it to boot.'),
                 ('Continue', 'Press Continue when the front panel is ready. The program will reconnect over USB.')])
        self.app.request('reconnect_scope', None)
        return (1.0 if ok else 0.0), dict(log=log[:400])

    def do_spc(self, p):
        self.wire(('SPC',), 'Signal path compensation', [('Disconnect', 'Disconnect everything from the oscilloscope inputs (including the RF input).'),
                  ('Warm up', 'The oscilloscope must have been operating for 20 minutes. SPC takes 5 to 15 minutes; repeat it if the temperature changes by more than 10 degrees C.')])
        self.io.scope.default_setup()
        self.status('Running signal path compensation (5-15 minutes) ...')
        ok, st = self.io.scope.run_spc()
        return (1.0 if ok else 0.0), dict(status=st)

    # ---- input impedance --------------------------------------------------------------------------------------------------------
    def do_imp(self, p):
        ch = p['ch']
        label = 'AUX IN' if ch == 'AUX' else f'CH{ch}'
        self.wire(('IMP', ch), f'Input impedance - {label}', [
            ('Disconnect', 'Remove all other cables and terminators from the oscilloscope inputs.'),
            ('Connect', f'Fluke 5560A SCOPE connector directly to the {label} input (the 5560A is switched to its resistance-measurement function).')],
            caution='Do not connect anything else to the input while measuring resistance.')
        cal = self.io.cal
        cal.standby_quiet()
        cal.select_scope_measure_resistance()
        scope = self.io.scope
        if ch != 'AUX':
            self.fresh_scope(('IMP', ch, p['term']))
            scope.select_only(ch)
            if p['term'] == '250k':
                self.ask('250 kΩ termination', f'Select 250 kΩ on {label}', [
                    ('Front panel', 'Push Utility, then Utility Page, then Self Test.'),
                    ('250 kΩ', 'Push the "250 kΩ Termination Verification" lower-bezel button, then the CH side-bezel button to enable the channel.'),
                    ('Scale', 'Set the vertical scale to 100 mV/div.')], ok='250 kΩ selected - measure')
            else:
                scope.channel(ch, term=p['term'], vscale=p['vscale'], bw=None, position=0.0)
        else:
            self.ask('AUX IN', 'AUX IN impedance', [('Front panel', 'Select the 250 kΩ termination verification as above so the AUX IN input is at 250 kΩ.')], ok='Selected - measure')
        pause(2.0)
        vals = [cal.measure_scope_resistance() for _ in range(3)]
        return sum(vals) / len(vals), dict(readings=vals)

    # ---- scope DC setups -----------------------------------------------------------------------------------------------------------
    def dc_setup(self, ch, term, bw, vscale, offset=0.0, hscale=1e-3):
        s = self.io.scope
        s.select_only(ch)
        s.channel(ch, term=term, bw=bw, vscale=vscale, offset=offset, position=0.0)
        s.timebase(hscale)
        s.trigger_line()
        s.acquire_mode('AVErage', 16)
        s.check_errors('DC setup')

    def do_bal(self, p):
        ch = p['ch']
        self.wire(('BAL', ch), f'DC balance - CH{ch}', [('Terminate', f'Remove all signal cables. Fit a 50 Ω terminator on the CH{ch} input and nothing else.')])
        self.fresh_scope(('BAL', ch))
        self.dc_setup(ch, p['term'], p['bw'], p['vscale'])
        return self.io.scope.mean_of(ch), {}

    # ---- DC gain ---------------------------------------------------------------------------------------------------------------------
    def dc_source(self, term):
        cal = self.io.cal
        cal.standby_quiet()
        cal.select_scope_dcv('50' if term == '50' else '1M')

    def apply_dc(self, volts):
        cal = self.io.cal
        cal.set_dc_volts(volts)
        cal.check_error(f'{volts:g} V')
        cal.operate()
        pause(2.0)

    def do_gain(self, p):
        ch = p['ch']
        self.wire(('DCV', ch), f'DC gain - CH{ch}', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Fluke 5560A SCOPE output to CH{ch} with the BNC cable (SCOPE DCV, source impedance matched to the input termination).')])
        self.fresh_scope(('GAIN', ch))
        self.dc_setup(ch, p['term'], p['bw'], p['vscale'])
        self.dc_source(p['term'])
        s = self.io.scope
        self.apply_dc(p['vneg']); vneg_m = s.mean_of(ch)
        self.apply_dc(p['vpos']); vpos_m = s.mean_of(ch)
        self.io.cal.standby_quiet()
        vdiff = abs(vneg_m - vpos_m)
        gain = (vdiff - p['vdiff']) / p['vdiff'] * 100.0           # Gain accuracy = (Vdiff - Vdiff_expected) / Vdiff_expected x 100 %
        return gain, dict(vneg_set=p['vneg'], vpos_set=p['vpos'], vneg_meas=vneg_m, vpos_meas=vpos_m, vdiff=vdiff, vdiff_expected=p['vdiff'])

    # ---- DC offset ---------------------------------------------------------------------------------------------------------------------
    def do_offset(self, p):
        ch = p['ch']
        self.wire(('OFF', ch), f'DC offset - CH{ch}', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Fluke 5560A SCOPE output to CH{ch}.')])
        self.fresh_scope(('OFF', ch))
        self.dc_setup(ch, p['term'], p['bw'], p['vscale'], offset=p['offset'])
        self.dc_source(p['term'])
        if abs(p['offset']) >= 50 and self._wired_hv != (ch, p['term']):
            self.ask('HIGH VOLTAGE', f'{abs(p["offset"]):g} V DC output', [('Safety', 'The next points apply up to 99.5 V DC. Check the cable and connector are rated, keep clear of the connection, and never touch the BNC while the output is on.')],
                     caution='Output stays in STANDBY until you continue.', ok='Enable output')
            self._wired_hv = (ch, p['term'])
        self.apply_dc(p['offset'])
        reading = self.io.scope.mean_of(ch)
        self.io.cal.standby_quiet()
        return reading, dict(applied=p['offset'])

    _wired_hv = None

    # ---- analog bandwidth ------------------------------------------------------------------------------------------------------------
    def do_bw(self, p):
        ch = p['ch']
        self.wire(('LEV', ch), f'Analog bandwidth - CH{ch}', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Fluke 5560A SCOPE output (leveled sine) to CH{ch}. Use the 50 Ω cable supplied for the 5560A leveled-sine head.')])
        s, cal = self.io.scope, self.io.cal
        self.fresh_scope(('BW', ch))
        s.select_only(ch)
        s.channel(ch, term=p['term'], bw='FULl', vscale=p['vscale'], offset=0.0, position=0.0)
        s.acquire_mode('SAMple')
        s.trigger_edge(f'CH{ch}', mode='AUTO')
        cal.standby_quiet(); cal.select_scope_levsine()
        cal.set_levsine(p['vin_pp'], p['ref_hz']); cal.check_error('levsine reference'); cal.operate_unverified(); pause(2.0)
        s.timebase(10e-6)
        s.measure_setup('PK2pk', f'CH{ch}')
        s.stats_reset(weighting=16); pause(3.0)
        vin = s.stat_mean()                                  # Vin-pp at 50 kHz
        s.timebase(p['hscale'])
        cal.set_levsine(p['vin_pp'], p['freq']); cal.check_error('levsine at bandwidth'); pause(2.0)
        s.stats_reset(weighting=16); pause(3.0)
        vbw = s.stat_mean()                                  # Vbw-pp at the bandwidth frequency
        cal.standby_quiet()
        gain = vbw / vin                                     # Gain = Vbw-pp / Vin-pp (must be >= 0.707)
        return gain, dict(vin_pp=vin, vbw_pp=vbw, gain=gain)

    # ---- random noise -----------------------------------------------------------------------------------------------------------------
    def do_noise(self, p):
        ch = p['ch']
        self.wire(('NOISE', ch), f'Random noise - CH{ch}', [('Disconnect', 'Disconnect everything from the oscilloscope inputs. Leave the inputs open.')])
        s = self.io.scope
        self.fresh_scope(('NOISE', ch))
        s.select_only(ch)
        s.channel(ch, term=p['term'], bw=p['bw'], vscale=p['vscale'], offset=0.0, position=0.0)
        s.write('MEASUrement:GATing NONE')
        s.measure_setup('RMS', f'CH{ch}')
        s.acquire_mode('SAMple'); s.stats_reset(weighting=64); pause(4.0)
        smv = s.stat_mean()                                  # Sampled Mean Value
        s.acquire_mode('AVErage', 16); s.stats_reset(weighting=64); pause(6.0)
        amv = s.stat_mean()                                  # Averaged Mean Value
        s.acquire_mode('SAMple')
        return smv - amv, dict(smv=smv, amv=amv)             # RMS noise = SMV - AMV

    # ---- reference frequency ---------------------------------------------------------------------------------------------------
    def need(self, inst, name):
        if inst is None:
            raise Skip(f'{name} is not configured')
        return inst

    def do_reffreq(self, p):
        gen = self.need(self.io.gen, 'the function generator (33220A / 33250A)')
        self.wire(('REF',), 'Reference frequency error', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', 'Function generator output to CH1 with a 50 Ω cable (the program sets a 2.5 Hz square wave = 400 ms mark period, 2 V p-p).'),
                  ('Accuracy', 'The generator time base must be at least 4x better than the limit. Lock it to a 10 MHz reference if it is not already.')])
        s = self.io.scope
        self.fresh_scope(('REF',))
        gen.square(1.0 / p['period'], 2.0)
        s.select_only(1)
        s.channel(1, term='50', vscale=0.5, offset=0.0, position=0.0)
        s.timebase(20e-3)
        s.trigger_edge('CH1', level=0.0, mode='NORMal')
        gen.output(True); pause(2.0)
        s.delay(p['period'])
        s.timebase(200e-9)
        pause(2.0)
        edge = s.edge_time(1)
        gen.output(False)
        return edge - p['period'], dict(edge_time=edge)

    # ---- delta time --------------------------------------------------------------------------------------------------------------------
    def source_options(self, freq, vpp):
        """Stimulus candidates in order of preference: the 5560A leveled sine when it can make the point, then the function generator."""
        opts = []
        if SOURCE_5560A['f_min'] <= freq <= SOURCE_5560A['f_max'] and vpp <= SOURCE_5560A['vpp_max']:
            opts.append('5560A')
        gen = self.io.gen
        if gen and freq <= gen.max_hz:
            opts.append('GEN')
        if not opts:
            raise Skip(f'{freq:g} Hz at {vpp:g} V p-p is outside the 5560A leveled sine'
                       + (f' and the {gen.kind} range' if gen else ' and no function generator is configured'))
        return opts

    def sine_source(self, ch, freq, vpp, label):
        """Wire and enable the first source that accepts the setting; if the 5560A rejects it, fall back to the generator."""
        errors = []
        for src in self.source_options(freq, vpp):
            self.source_wire(src, ch, label)
            try:
                self.apply_sine(src, freq, vpp)
                return src
            except drivers.InstrumentError as exc:
                self.io.all_outputs_off(); errors.append(f'{src}: {exc}'); self._wired = None
        raise Skip('; '.join(errors))

    def source_wire(self, src, ch, label):
        if src == '5560A':
            self.wire(('SRC5560', ch), f'{label} - CH{ch}', [('Connect', f'Fluke 5560A SCOPE output (leveled sine) to CH{ch}.')])
        else:
            self.wire(('SRCGEN', ch), f'{label} - CH{ch}', [('Connect', f'Function generator ({self.io.gen.kind}) output to CH{ch} with a 50 Ω cable.')])

    def apply_sine(self, src, freq, vpp):
        if src == '5560A':
            cal = self.io.cal
            cal.standby_quiet(); cal.select_scope_levsine(); cal.set_levsine(vpp, freq); cal.check_error('levsine'); cal.operate_unverified()
        else:
            self.io.gen.sine(freq, vpp); self.io.gen.output(True)
        pause(2.0)

    def do_delta(self, p):
        ch = p['ch']
        s = self.io.scope
        self.fresh_scope(('DT', ch))
        s.select_only(ch)
        s.channel(ch, term='50', vscale=p['vscale'], offset=0.0, position=0.0)
        s.timebase(p['hscale'])
        s.trigger_edge(f'CH{ch}', mode='AUTO')
        s.acquire_mode('SAMple')
        src = self.sine_source(ch, p['freq'], p['vpp'], 'Delta time')
        sd = s.delay_stddev(ch, samples=100, wait=8.0)
        return sd, dict(source=src)

    # ---- digital threshold ----------------------------------------------------------------------------------------------------------
    def find_edge(self, d, centre, rising):
        """Smallest grid voltage (10 mV) where D<d> is static HIGH when `rising`, or largest where it is static LOW otherwise."""
        s = self.io.scope
        step = 0.010
        grid = lambda v: round(round(v / step) * step, 6)
        lo, hi = grid(centre - 0.4), grid(centre + 0.4)
        want_high = lambda v: (self.apply_dc(v), s.digital_state(d, settle=3.0))[1]
        # make sure the bracket really straddles the threshold (manual: start at +/-400 mV, widen to +/-500 mV)
        for _ in range(4):
            if want_high(lo) != 'low': lo = grid(lo - 0.1)
            else: break
        for _ in range(4):
            if want_high(hi) != 'high': hi = grid(hi + 0.1)
            else: break
        while round((hi - lo) / step) > 1:
            self.check()
            mid = grid((lo + hi) / 2)
            state = want_high(mid)
            if rising:
                if state == 'high': hi = mid
                else: lo = mid
            else:
                if state == 'low': lo = mid
                else: hi = mid
        return hi if rising else lo

    def do_digital(self, p):
        d = int(p['ch'][1:])
        self.wire(('DIG', d), f'Digital threshold - D{d}', [
            ('Disconnect', 'Remove other cables. The P6616 logic probe must be connected to the oscilloscope.'),
            ('Connect', f'Fluke 5560A SCOPE output to probe channel D{d} through the BNC-to-0.1 inch pin adapter. Connect the ground lead of the same probe pod too.')])
        s, cal = self.io.scope, self.io.cal
        self.fresh_scope(('DIG', d))
        s.digital_on()
        s.digital_threshold(d, p['threshold'])
        s.timebase(4e-6)
        s.trigger_edge(f'D{d}', mode='NORMal')
        cal.standby_quiet(); cal.select_scope_dcv('1M'); cal.set_dc_volts(p['threshold']); cal.operate()
        vs_minus = self.find_edge(d, p['threshold'], rising=True)       # Vs-: first static HIGH when increasing
        vs_plus = self.find_edge(d, p['threshold'], rising=False)       # Vs+: first static LOW when decreasing
        cal.standby_quiet()
        return (vs_minus + vs_plus) / 2.0, dict(vs_minus=vs_minus, vs_plus=vs_plus)      # VsAvg = (Vs- + Vs+) / 2

    # ---- RF -------------------------------------------------------------------------------------------------------------------------------
    def rf_out(self, inst, f, level):
        inst.set_rf(f, level)
        inst.output(True)

    def do_phase(self, p):
        rf = self.need(self.io.rf1, 'the Fluke 96270A')
        self.wire(('RF',), 'RF input', [('Disconnect', 'Remove other cables.'), ('Connect', '96270A RF output to the oscilloscope RF input with a 50 Ω SMA cable.')])
        s = self.io.scope
        self.rf_out(rf, 1e9, 0.0); pause(2.0)
        s.rf_setup(center=1e9, span=p['span'], rbw=p['rbw'], ref_level=0.0, averages=16)
        pause(8.0)
        rbw = s.rf_rbw()
        xs, ys = s.rf_trace(True)
        f_pk, l_pk = trace_peak(xs, ys)
        half = max(p['span'] / 200, rbw)
        vals = [y for x, y in zip(xs, ys) if abs(x - (f_pk + p['offset_hz'])) <= half]
        if not vals:
            raise Skip('offset lies outside the acquired span')
        l_off = 10 * math.log10(sum(10 ** (v / 10) for v in vals) / len(vals))
        rf.output(False)
        return (l_off - l_pk) - 10 * math.log10(rbw * ENBW_FACTOR), dict(peak_dbm=l_pk, offset_dbm=l_off, rbw=rbw)

    def do_danl(self, p):
        label = 'TPA-N-PRE input' if p.get('tpa') else 'RF input'
        self.wire(('DANL', bool(p.get('tpa'))), f'DANL - {label}', [('Terminate', f'Fit a 50 Ω N terminator on the {label} and make sure no signal is applied.')]
                  + ([('TPA-N-PRE', 'Push Menu on the TPA-N-PRE; on the oscilloscope set Mode to Auto.')] if p.get('tpa') else []))
        s = self.io.scope
        s.rf_setup(start=p['f_start'], stop=p['f_stop'], ref_level=p['ref_level'], averages=32)
        pause(60.0 if p['f_start'] < 50e3 else 20.0)
        xs, ys = s.rf_trace(True)
        f_pk, l_pk = noise_floor_max(xs, ys)
        if p['f_start'] >= 5e6:                               # narrow to a 10 MHz span at the noisiest frequency, as the manual does
            s.rf_setup(center=f_pk, span=10e6, ref_level=p['ref_level'], averages=32)
            pause(20.0)
            xs, ys = s.rf_trace(True)
            f_pk, l_pk = noise_floor_max(xs, ys)
        rbw = s.rf_rbw()
        return to_per_hz(l_pk, rbw), dict(noise_dbm=l_pk, at_hz=f_pk, rbw=rbw)

    def do_absamp(self, p):
        rf = self.need(self.io.rf1, 'the Fluke 96270A')
        self.wire(('RFAMP',), 'Absolute amplitude', [('Connect', '96270A RF output to the oscilloscope RF input with a 50 Ω SMA cable (through the power splitter if a power meter is used).')])
        s = self.io.scope
        level = p['level_dbm']
        worst, rows = 0.0, []
        f = p['f_start']
        s.rf_setup(center=f, span=p['span'], ref_level=level, averages=None, average_trace=False)
        while f <= p['f_stop'] * (1 + 1e-9):
            self.check()
            rf.set_rf(f, level); rf.output(True)
            s.rf_cmd('center', v=f); s.rf_cmd('span', v=p['span'])
            pause(1.5)
            xs, ys = s.rf_trace(False)
            _fx, l_scope = trace_peak(xs, ys, f, p['span'] / 10)
            ref = self.reference_level(f, level, p)
            diff = l_scope - ref
            rows.append((f, diff))
            if abs(diff) > abs(worst): worst = diff
            f += p['f_step']
        rf.output(False)
        return worst, dict(points=len(rows), worst_hz=max(rows, key=lambda r: abs(r[1]))[0])

    def reference_level(self, f, level, p):
        """Reference power: the power meter if one is configured, else the 96270A's calibrated output level."""
        if self.io.power:
            return self.io.power.power()
        return level

    def do_imd(self, p):
        rf1 = self.need(self.io.rf1, 'the Fluke 96270A')
        rf2 = self.need(self.io.rf2, 'a second RF source')
        self.wire(('IMD',), 'Third-order intermodulation', [('Combine', 'Connect both RF sources to the two -3 dB inputs of the hybrid coupler (Krytar 3005070). Coupler IN to the oscilloscope RF input with an SMA cable.')])
        s = self.io.scope
        rf1.set_rf(p['f1'], -10.0); rf2.set_rf(p['f2'], -10.0); rf1.output(True); rf2.output(True); pause(2.0)
        s.rf_setup(center=p['center'], span=100e6, rbw=100e3, ref_level=0.0, averages=16)
        pause(10.0)
        xs, ys = s.rf_trace(True)
        _f, l1 = trace_peak(xs, ys, p['f1'], 2e6)
        target = p['f1'] - 20e6 if p['which'] == 'low' else p['f2'] + 20e6
        _f, ls = trace_peak(xs, ys, target, 2e6)
        rf1.output(False); rf2.output(False)
        return ls - l1, dict(f1_dbm=l1, spur_dbm=ls)

    def do_spur(self, p):
        self.wire(('SPUR',), 'Residual spurious response', [('Terminate', 'Fit a 50 Ω N terminator on the RF input and make sure no signal is applied.')])
        s = self.io.scope
        s.rf_setup(start=p['f_start'] if not p['at_freq'] else p['at_freq'] - 5e6, stop=p['f_stop'] if not p['at_freq'] else p['at_freq'] + 5e6,
                   rbw=p['rbw'], ref_level=-25.0, averages=32)
        pause(60.0 if p['f_start'] < 50e3 else 30.0)
        xs, ys = s.rf_trace(True)
        if p['at_freq']:
            _f, lvl = trace_peak(xs, ys, p['at_freq'], 1e6)
        else:
            best = max_excluding(xs, ys, p['exclude'], 1e6)
            _f, lvl = best
        return lvl, dict(at_hz=_f)

    def do_xtalk(self, p):
        rf = self.need(self.io.rf1, 'the Fluke 96270A')
        ch = p['ch']
        self.wire(('XT', ch), f'Crosstalk - CH{ch}', [('Terminate', 'Fit a 50 Ω terminator on the RF input.'),
                  ('Connect', f'96270A output to CH{ch} (50 Ω input). Leave the other analog channels unconnected.')])
        s = self.io.scope
        s.default_setup() if self._scope_ctx != ('XT', ch) else None
        self._scope_ctx = ('XT', ch)
        for n in (1, 2, 3, 4):
            s.write(f'CH{n}:TERmination 50.0')
        rf.set_rf(p['freq'], 0.0); rf.output(True)
        s.rf_setup(center=p['freq'], span=50e6, averages=16)
        pause(10.0)
        xs, ys = s.rf_trace(True)
        _f, lvl = trace_peak(xs, ys, p['freq'], 2e6)
        rf.output(False)
        return lvl, {}

    def do_tpafunc(self, p):
        rf = self.need(self.io.rf1, 'the Fluke 96270A')
        self.wire(('TPA',), 'TPA-N-PRE functional check', [('Connect', '96270A RF output to the TPA-N-PRE input (through the power splitter if a power meter is used). The TPA-N-PRE must be attached to the oscilloscope RF input.'),
                  ('TPA-N-PRE', 'Push Menu on the TPA-N-PRE; on the oscilloscope set Mode to Auto.')])
        s = self.io.scope
        rf.set_rf(p['freq'], p['level_dbm']); rf.output(True)
        s.rf_setup(center=p['freq'], span=p['span'], ref_level=p['ref_level'], average_trace=False)
        pause(4.0)
        xs, ys = s.rf_trace(False)
        _f, l_scope = trace_peak(xs, ys, p['freq'], p['span'] / 10)
        ref = self.reference_level(p['freq'], p['level_dbm'], p)
        rf.output(False)
        return l_scope - ref, dict(scope_dbm=l_scope, reference_dbm=ref)

    # ---- trigger output -----------------------------------------------------------------------------------------------------------------
    def do_trigout(self, p):
        self.wire(('TRIG',), 'Trigger output', [('Disconnect', 'Remove other cables.'), ('Connect', 'Rear-panel TRIGGER OUT to CH1 with a 50 Ω BNC cable.')])
        s = self.io.scope
        self.fresh_scope(('TRIG',))
        s.select_only(1)
        s.channel(1, term=p['term'], vscale=1.0, offset=0.0, position=0.0)
        s.measure_setup('HIGH' if p['state'] == 'HIGH' else 'LOW', 'CH1')
        s.acquire_mode('SAMple'); s.stats_reset(weighting=16); pause(3.0)
        return s.stat_mean(), {}

    # ---- AFG -------------------------------------------------------------------------------------------------------------------------------
    def meter(self, kind, p, prompt):
        inst = {'freq': self.io.counter or self.io.dmm, 'ac': self.io.dmm, 'dc': self.io.dmm}[kind]
        if inst is None:
            return self.manual(prompt, p['unit'], p)
        return {'freq': inst.frequency, 'ac': inst.ac_rms, 'dc': inst.dc}[kind]()

    def do_afgfreq(self, p):
        self.wire(('AFGF',), 'AFG frequency', [('Connect', 'AFG output to the frequency counter input (50 Ω).')])
        s = self.io.scope
        self.fresh_scope(('AFG',))
        s.afg_set(p['wave'], frequency=p['nominal'], vpp=p['vpp'], offset=0.0)
        pause(2.0)
        v = self.meter('freq', p, f'Enter the counter reading for {p["desc"]}')
        s.afg_off()
        return v, {}

    def do_afgamp(self, p):
        self.wire(('AFGA',), 'AFG amplitude', [('Connect', 'AFG output to the DMM through a 50 Ω feed-through termination. Set the DMM to AC volts (rms).')])
        s = self.io.scope
        self.fresh_scope(('AFG',))
        s.afg_set('SQUare', frequency=p['freq'], vpp=p['vpp'], offset=p['offset'])
        pause(2.0)
        v = self.meter('ac', p, f'Enter the DMM AC reading for {p["desc"]}')
        s.afg_off()
        return v, {}

    def do_afgoff(self, p):
        self.wire(('AFGO',), 'AFG DC offset', [('Connect', 'AFG output to the DMM through a 50 Ω feed-through termination. Set the DMM to DC volts.')])
        s = self.io.scope
        self.fresh_scope(('AFG',))
        s.afg_set('DC', offset=p['level'])
        pause(2.0)
        v = self.meter('dc', p, f'Enter the DMM DC reading for {p["desc"]}')
        s.afg_off()
        return v, {}

    # ---- DVM ---------------------------------------------------------------------------------------------------------------------------------
    def do_dvmdc(self, p):
        ch = p['ch']
        self.wire(('DVMDC', ch), f'DVM DC - CH{ch}', [('Disconnect', 'Remove other cables.'), ('Connect', f'Fluke 5560A SCOPE output to CH{ch} (1 MΩ).')])
        s = self.io.scope
        self.fresh_scope(('DVMDC', ch))
        self.dc_setup(ch, '1M', 'TWEnty', p['vscale'], offset=p['offset'])
        s.dvm('DC', ch)
        self.dc_source('1M')
        self.apply_dc(p['nominal'])
        v = s.dvm_value()
        self.io.cal.standby_quiet()
        return v, {}

    def do_dvmac(self, p):
        ch = p['ch']
        self.wire(('DVMAC', ch), f'DVM AC - CH{ch}', [('Disconnect', 'Remove other cables.'), ('Connect', f'Fluke 5560A SCOPE output (square wave) to CH{ch} (50 Ω).')])
        s, cal = self.io.scope, self.io.cal
        self.fresh_scope(('DVMAC', ch))
        s.select_only(ch)
        s.channel(ch, term='50', vscale=p['vscale'], offset=0.0, position=0.0)
        s.dvm('ACRMS', ch)
        cal.standby_quiet(); cal.select_scope_square(); cal.set_square(p['vpp'], p['freq']); cal.check_error('square wave'); cal.operate_unverified()
        pause(2.0)
        v = s.dvm_value()
        cal.standby_quiet()
        return v, {}

    def do_dvmfreq(self, p):
        ch = p['ch']
        s = self.io.scope
        self.fresh_scope(('DVMF', ch))
        s.select_only(ch)
        s.channel(ch, term='50', vscale=0.5, offset=0.0, position=0.0)
        s.timebase(20e-3)
        s.trigger_edge(f'CH{ch}', mode='AUTO')
        s.dvm('FREQuency', ch)
        src = self.sine_source(ch, p['freq'], 1.0, 'DVM frequency')
        v = s.dvm_frequency()
        return v, dict(source=src)


# ======================================================================================================================
# the application window
# ======================================================================================================================
class App(datamode.DataModeMixin):
    def __init__(self, root, demo=False):
        self.root, self.demo = root, demo
        self.io = None
        self._busy = False
        self.stop = False
        self.results = {}
        self.q = queue.Queue()
        self.cfg = Config()
        ui.apply_theme(root)
        root.title('Tektronix MDO4000C | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1380, 880, min_w=900, min_h=680)
        self.settings = ui.Settings('MDO4000C')
        g = self.settings.get
        self.asset, self.serial = tk.StringVar(), tk.StringVar()
        self.v_model = tk.StringVar(value=g('model', '4104C'))
        self.v_sa = tk.StringVar(value=g('sa', 'None'))
        self.v_afg = tk.BooleanVar(value=g('afg', 'False') == 'True')
        self.v_dvm = tk.BooleanVar(value=g('dvm', 'False') == 'True')
        self.v_dig = tk.BooleanVar(value=g('dig', 'True') == 'True')
        self.v_tpa = tk.BooleanVar(value=g('tpa', 'False') == 'True')
        self.addr = {k: tk.StringVar(value=g(k, d)) for k, d in (
            ('scope', 'USB0::0x0699::0x0415::C000000::INSTR'), ('cal', 'COM9'), ('cal_baud', '9600'), ('rf1', ''), ('rf2', ''), ('gen', ''), ('dmm', ''), ('counter', ''), ('power', ''))}
        self.status = tk.StringVar()
        self.detail = tk.StringVar(value='Select a test point to see its limits and setup.')
        self.show_section = tk.StringVar(value='All sections')
        self.show_status = tk.StringVar(value='All points')
        self._build_ui()
        self.on_config(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument.' if demo else
                        'Step 1: instrument ID and model/options. Step 2: addresses, then Test Connections. Step 3: Run All Pending.')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.bind('<Control-s>', lambda _e: self.save())
        import labregistry
        labregistry.attach(root, self.asset, self.serial, self.status.set)
        self.root.after(50, self._pump)

    # ---- selection ---------------------------------------------------------------------------------------------------
    def read_cfg(self):
        self.cfg = Config(self.v_model.get(), self.v_sa.get(), self.v_afg.get(), self.v_dvm.get(), self.v_dig.get(), self.v_tpa.get())
        if self.cfg.model == '4024C' and False:
            pass
        return self.cfg

    def active_points(self):
        return [p for p in POINTS if self.cfg.applies(p)]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, v):
        self._busy = v
        if hasattr(self, 'btn_run'): self._sync_buttons()

    def _sync_buttons(self):
        idle = 'disabled' if self._busy else 'normal'
        for b in (self.btn_run, self.btn_section, self.btn_rerun, self.btn_test, self.btn_load, self.btn_find, *self.mode_buttons):
            b.configure(state=idle)
        self.btn_stop.configure(state='normal' if self._busy else 'disabled')
        for c in self.cfg_widgets:
            c.configure(state='disabled' if self._busy else ('readonly' if isinstance(c, ttk.Combobox) else 'normal'))

    # ---- layout -------------------------------------------------------------------------------------------------------------
    def _build_ui(self):
        root = self.root
        sh = self.shell = ui_shell.Shell(root, 'Tektronix MDO4000C  -  Performance Verification',
                                         f'MDO4024C / 4034C / 4054C / 4104C  |  {SPEC["source"]["document"]}  |  {len(POINTS)} points in the spec',
                                         demo=self.demo, on_section=self.pick_section, version='spec v2')
        self.status = sh.status_var
        self.conn_pill = sh.add_chip('Not connected', 'neutral')
        sh.build_identity(self.asset, self.serial)
        self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
        self.summary = sh.build_progress()
        if self.demo: sh.notice('Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode')
        else: sh.notice('The program stops and asks you to confirm every cable, terminator, instrument or front-panel change before the next point. '
                        'Stay at the bench: high-voltage DC points (to 99.5 V) and RF outputs are enabled only after you confirm.', 'info')

        d = sh.drawer_body; d.columnconfigure(1, weight=1)
        ttk.Label(d, text='Model').grid(row=0, column=0, sticky='w', pady=4)
        m = ttk.Combobox(d, textvariable=self.v_model, values=['MDO' + x for x in MODELS], width=10, state='readonly'); m.grid(row=0, column=1, padx=(10, 0), pady=4, sticky='w')
        m.set('MDO' + self.v_model.get().replace('MDO', ''))
        ttk.Label(d, text='Spectrum analyzer').grid(row=1, column=0, sticky='w', pady=4)
        sa = ttk.Combobox(d, textvariable=self.v_sa, values=['None', 'SA3', 'SA6'], width=10, state='readonly'); sa.grid(row=1, column=1, padx=(10, 0), pady=4, sticky='w')
        checks = [ttk.Checkbutton(d, text='AFG (MDO4AFG)', variable=self.v_afg, command=self.on_config),
                  ttk.Checkbutton(d, text='DVM', variable=self.v_dvm, command=self.on_config),
                  ttk.Checkbutton(d, text='Digital channels (P6616)', variable=self.v_dig, command=self.on_config),
                  ttk.Checkbutton(d, text='TPA-N-PRE attached', variable=self.v_tpa, command=self.on_config)]
        for i, c in enumerate(checks): c.grid(row=2 + i, column=0, columnspan=2, sticky='w', pady=1)
        self.btn_read_opts = ttk.Button(d, text='Read options from scope', command=self.read_options); self.btn_read_opts.grid(row=6, column=0, columnspan=2, sticky='w', pady=(8, 0))
        self.cfg_widgets = [m, sa] + checks
        for w in (m, sa): w.bind('<<ComboboxSelected>>', lambda _e: self.on_config())
        ttk.Separator(d).grid(row=7, column=0, columnspan=2, sticky='ew', pady=(12, 10))
        rows = [('scope', 'MDO4000C (USB)'), ('cal', 'Fluke 5560A'), ('rf1', 'Fluke 96270A (RF)'), ('rf2', 'RF source 2 (IMD only)'),
                ('gen', 'Agilent 33220A / 33250A'), ('dmm', 'Reference DMM (AFG)'), ('counter', 'Counter (AFG freq)'), ('power', 'Power meter (optional)')]
        self.addr_boxes = {}
        for i, (key, label) in enumerate(rows):
            ttk.Label(d, text=label).grid(row=8 + i, column=0, sticky='w', pady=4)
            cb = ttk.Combobox(d, textvariable=self.addr[key], state='normal', width=34); cb.grid(row=8 + i, column=1, sticky='ew', padx=(10, 0), pady=4)
            self.addr_boxes[key] = cb
        ttk.Label(d, text='5560A baud').grid(row=16, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.addr['cal_baud'], values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=16, column=1, sticky='w', padx=(10, 0), pady=4)
        ttk.Label(d, text='Leave an address blank if that instrument is not used. Without a reference DMM / counter the AFG readings are typed in.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=17, column=0, columnspan=2, sticky='w', pady=(8, 0))
        btns = sh.drawer_footer
        self.btn_find = ttk.Button(btns, text='Find instruments', command=self.find_instruments); self.btn_find.pack(side='left', padx=(0, 8))
        self.btn_test = ttk.Button(btns, text='Test connections', command=self.test_connections, style='Accent.TButton'); self.btn_test.pack(side='left')

        self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
        self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
        self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
        self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
        sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
        sh.add_action('Export CSV', self.export_csv, side='right', short='CSV')
        self.btn_load = sh.add_action('Load progress', self.load, side='right', short='Load')
        sh.add_action('Save progress', self.save, side='right', short='Save')

        body = sh.content
        info = ttk.Frame(body); info.pack(side='bottom', fill='x', pady=(8, 0))
        ttk.Label(info, textvariable=self.detail, wraplength=1100, justify='left', style='Muted.TLabel').pack(anchor='w', fill='x')
        filt = ttk.Frame(body); filt.pack(side='top', fill='x', pady=(0, 6))
        ttk.Label(filt, text='Test points', style='Bold.TLabel').pack(side='left')
        c2 = ttk.Combobox(filt, textvariable=self.show_status, values=datamode.STATUS_FILTERS + ['Skipped'], width=14, state='readonly'); c2.pack(side='right')
        ttk.Label(filt, text='Show', style='Muted.TLabel').pack(side='right', padx=(0, 6))
        c2.bind('<<ComboboxSelected>>', lambda _e: self.refresh())
        self.tree = ui_shell.results_table(self, body)
        ui_shell.small_window(self, self.tree, filt)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        ui.polish(root)

    # ---- configuration changed -------------------------------------------------------------------------------------------------
    def on_config(self, save=True):
        self.v_model.set(self.v_model.get().replace('MDO', ''))
        self.read_cfg()
        if save:
            for k, v in (('model', self.v_model.get()), ('sa', self.v_sa.get()), ('afg', str(self.v_afg.get())), ('dvm', str(self.v_dvm.get())),
                         ('dig', str(self.v_dig.get())), ('tpa', str(self.v_tpa.get()))):
                self.settings.set(k, v)
            self.settings.save()
        self.refresh()

    def read_options(self):
        if self.demo:
            messagebox.showinfo('Demo mode', 'Demo mode uses no hardware.'); return
        if self.io is None: self.test_connections()
        if self.io is None: return
        opts = self.io.scope.installed_options()
        model = self.io.scope.model
        if model in MODELS: self.v_model.set(model)
        self.v_sa.set('SA6' if 'SA6' in opts else 'SA3' if 'SA3' in opts else 'None')
        self.v_afg.set('AFG' in opts); self.v_dvm.set('DVM' in opts)
        self.on_config()
        messagebox.showinfo('Options read', f'Model MDO{model}; options reported: {", ".join(sorted(opts)) or "none"}.\nCheck the boxes against the instrument label and correct anything the scope does not report.')

    # ---- table --------------------------------------------------------------------------------------------------------------------
    def _visible(self, p):
        if not self.cfg.applies(p): return False
        rec = self.results.get(str(p['id']), {}); res = rec.get('result', '')
        if self.show_section.get() not in ('All sections', SECTION_TITLE[p['section']]): return False
        st = self.show_status.get()
        if st == 'Not tested' and res: return False
        if st == 'Passed' and res != 'PASS': return False
        if st == 'Failed (OOT)' and res != 'FAIL': return False
        if not self.status_visible(str(p['id']), st): return False
        if st == 'Skipped' and res != 'SKIP': return False
        return True

    def _row(self, p):
        key = str(p['id']); rec = self.results.get(key, {}); res = rec.get('result', '')
        shown = {'PASS': '✔ PASS', 'FAIL': '✖ FAIL', 'SKIP': '⊘ skipped'}.get(res, '—')
        if p.get('passfail'):
            word = lambda r: '' if not r or r.get('reading') is None else ('Pass' if r['reading'] >= 0.5 else 'Fail')
            f, l = self.found.get(key), self.left.get(key)
            return (p['id'], p['desc'], 'Pass', '', '', 'Pass', word(f), '', word(l) or ('Same' if (self.is_left and f) else ''), shown), (res.lower() or 'pending',)
        unit = p['unit']
        fmt = (lambda v: fmt_plain(v, 5) + ' ' + unit) if unit in PLAIN_UNITS else (lambda v: ui.si(v, unit))
        cells, tags = self.shell_cells(key, p['nominal'], p['low'], p['high'], unit, fmt=fmt)
        cells = list(cells)
        if res == 'SKIP': cells[4:7] = ['', '', '']
        return (p['id'], p['desc'], *cells), tags

    def sections_now(self):
        return [p for p in POINTS if self.cfg.applies(p)]

    def refresh(self):
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for p in POINTS:
            if self._visible(p):
                v, tags = self._row(p); self.tree.insert('', 'end', iid=str(p['id']), values=v, tags=tags)
        if keep and self.tree.exists(keep[0]): self.tree.selection_set(keep[0])
        self.update_summary()

    def _update_row(self, p):
        iid = str(p['id'])
        if self.tree.exists(iid):
            v, tags = self._row(p); self.tree.item(iid, values=v, tags=tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(self.active_points())
        self.update_shell_sections(self.active_points(), lambda p: SECTION_TITLE[p['section']])

    def on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        nom, lo, hi, _r, unit = display_row(p)
        rec = self.results.get(str(p['id']), {})
        raw = rec.get('raw')
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        stim = {'none': 'no input signal', 'cal': 'Fluke 5560A', 'rf': 'Fluke 96270A', 'rf2': 'two RF sources', 'gen': 'function generator'}[p['stim']]
        work = ('\nWorksheet: ' + ', '.join(f'{k} = {v:.6g}' if isinstance(v, float) else f'{k} = {v}' for k, v in raw.items())) if raw else ''
        both = ('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''
        self.detail.set(f'{p["desc"]}\nLimits: {lo} to {hi} {unit}  |  Stimulus: {stim}  |  Manual page {SECTION_PAGE[p["section"]]}{extra}{work}{both}')

    # ---- connections ----------------------------------------------------------------------------------------------------------------
    def find_instruments(self):
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        for cb in self.addr_boxes.values(): cb['values'] = found
        self.status.set(f'{len(found)} VISA resource(s): ' + (', '.join(found) if found else 'none'))

    def addrs(self):
        return {k: v.get() for k, v in self.addr.items()}

    def test_connections(self):
        if self.demo: messagebox.showinfo('Demo mode', 'Demo mode uses no hardware.'); return
        self.status.set('Connecting ...'); self.root.update_idletasks()
        try:
            self.disconnect(); self.io = IO(self.addrs())
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); messagebox.showerror('Connection error', str(exc)); return
        self._set_conn(True); self._save_addrs()
        used = [n for n, o in (('96270A', self.io.rf1), ('RF source 2', self.io.rf2), ('function generator', self.io.gen), ('reference DMM', self.io.dmm), ('counter', self.io.counter), ('power meter', self.io.power)) if o]
        self.status.set('Connected: ' + self.io.ident + '. Outputs are OFF.')
        messagebox.showinfo('Connected', f'Oscilloscope: {self.io.ident}\nFluke 5560A: {self.io.cal.idn}\nAlso connected: {", ".join(used) or "no other instruments"}\nAll outputs are off.')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set('Connected' if ok else 'Connection failed' if ok is False else ('Demo - no hardware' if self.demo else 'Not connected'),
                               'good' if ok else 'bad' if ok is False else 'neutral')

    def _save_addrs(self):
        for k, v in self.addr.items(): self.settings.set(k, v.get())
        self.settings.save()

    # ---- thread <-> UI -----------------------------------------------------------------------------------------------------------------
    def post(self, kind, payload=None):
        self.q.put((kind, payload, None))

    def request(self, kind, payload):
        """Called on the worker thread: ask the main thread something and wait for the answer."""
        box = dict(ev=threading.Event(), value=None)
        self.q.put((kind, payload, box))
        while not box['ev'].wait(0.1):
            if self.stop and kind != 'reconnect_scope':
                raise Stopped()
        return box['value']

    def _pump(self):
        """Main thread: handle worker messages (the worker never touches Tk)."""
        try:
            while True:
                kind, payload, box = self.q.get_nowait()
                if kind == 'status': self.status.set(payload)
                elif kind == 'row': self._update_row(POINTS[payload - 1])
                elif kind == 'done': self._finished(payload)
                elif kind == 'ask':
                    ok = ui.confirm_steps(self.root, payload['title'], payload['heading'], payload['steps'], facts=payload['facts'], caution=payload['caution'], ok=payload['ok'])
                    box['value'] = ok; box['ev'].set()
                elif kind == 'manual':
                    box['value'] = self._manual_dialog(payload); box['ev'].set()
                elif kind == 'reconnect_scope':
                    box['value'] = self._reconnect(); box['ev'].set()
        except queue.Empty:
            pass
        self.root.after(50, self._pump)

    def _manual_dialog(self, req):
        from tkinter import simpledialog
        while True:
            text = simpledialog.askstring('Enter reading', req['prompt'] + f'\n(value in {req["unit"]}, plain number)', parent=self.root)
            if text is None: return None
            try: return float(text.replace(',', ''))
            except ValueError: messagebox.showwarning('Reading', 'Enter a number.')

    def _reconnect(self):
        try:
            return self.io.reconnect_scope()
        except Exception:
            return False

    # ---- running ---------------------------------------------------------------------------------------------------------------------------
    def request_stop(self): self.stop = True; self.status.set('Stopping after the current step.')
    def run_all(self): self.execute([p for p in self.active_points() if str(p['id']) not in self.results])

    def run_section(self): self.run_shown_section()

    def rerun(self):
        sel = self.tree.selection()
        if sel: self.execute([POINTS[int(sel[0]) - 1]])
        else: messagebox.showinfo('Selection', 'Select a test point first.')

    def execute(self, points):
        if not self.confirm_found_overwrite(points): return
        if self.busy or not points: return
        if not self.asset.get().strip(): messagebox.showwarning('Instrument ID', 'Enter an instrument ID.'); return
        self.read_cfg()
        if self.demo:
            for p in points:
                self._record(p, demo_reading(p), {}, True)
            self.status.set('Demo run complete.'); self.save(silent=True); return
        if self.io is None: self.test_connections()
        if self.io is None: return
        self.stop = False; self.busy = True
        threading.Thread(target=self._worker, args=(points,), daemon=True).start()

    def _worker(self, points):
        runner = Runner(self)
        error = None
        try:
            for i, p in enumerate(points, 1):
                if self.stop: raise Stopped()
                self.post('status', f'Running {i}/{len(points)}: {p["desc"]}')
                try:
                    reading, raw = runner.run_point(p)
                    self._record_threadsafe(p, reading, raw, False)
                except Skip as s:
                    self.results[str(p['id'])] = dict(result='SKIP', reason=str(s), timestamp=datetime.now().isoformat(timespec='seconds'))
                    self.post('row', p['id'])
        except Stopped:
            error = 'stopped'
        except BaseException as exc:
            error = exc
        finally:
            try: self.io.all_outputs_off()
            except Exception: pass
        self.post('done', error)

    def _finished(self, error):
        self.busy = False; self.save(silent=True)
        if error == 'stopped': self.status.set('Run stopped. Progress is saved.')
        elif error is not None:
            self.status.set('Error - run stopped: ' + str(error)); messagebox.showerror('Measurement stopped', str(error))
        else: self.status.set('Run complete. Save progress or export a report.')

    def _record_threadsafe(self, p, reading, raw, synthetic):
        raw = dict(raw, reading=reading)
        self.results[str(p['id'])] = dict(reading=reading, raw=raw, result=judge(p, reading), synthetic=synthetic,
                                          uncertainty=uncertainty_text(p, raw), timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label)
        self.post('row', p['id'])
        self.save(silent=True)

    def _record(self, p, reading, raw, synthetic):
        self._record_threadsafe(p, reading, raw, synthetic)
        self._update_row(p)

    # ---- files -------------------------------------------------------------------------------------------------------------------------------
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'MDO{self.cfg.model}_{name}_checkpoint.json')

    def save(self, silent=False):
        path = self._checkpoint_path()
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, config=self.cfg.as_dict(), **self.save_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not messagebox.askyesno('Synthetic data', 'The checkpoint contains DEMO results. Load for review only?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        c = data.get('config', {})
        self.v_model.set(c.get('model', self.v_model.get())); self.v_sa.set(c.get('sa', 'None'))
        for var, key in ((self.v_afg, 'afg'), (self.v_dvm, 'dvm'), (self.v_dig, 'dig'), (self.v_tpa, 'tpa')): var.set(bool(c.get(key, var.get())))
        self.load_results(data)
        self.on_config(save=False); self.status.set(f'Loaded progress: {len(self.found)} As Found and {len(self.left)} As Left point(s).')

    def certificate_row(self, p, r):
        """The report row of one recorded point (r = its record); None for a skipped point."""
        import report_pdf
        if not r or r['result'] not in ('PASS', 'FAIL'): return None
        failed = r['result'] == 'FAIL'
        unc = r.get('uncertainty') or uncertainty_text(p, r.get('raw', {}))
        sec = SECTION_TITLE[p['section']]
        if p.get('passfail'):
            return dict(Section=sec, Description=p['desc'], Nominal='Pass', **{'Tolerance -': 'N/A', 'Tolerance +': 'N/A'}, UOM='', **{'As Found': 'Pass' if not failed else 'Fail'},
                        OOT='OOT' if failed else '', **{'As Left': 'Same'}, Uncertainty='N/A')
        if p['unit'] in PLAIN_UNITS:
            nom, lo, hi, rd, unit = display_row(p, r['reading'])
            limit_text = nom if (p['low'] is not None and p['high'] is not None) else (('<= ' + hi + ' ' + unit) if p['high'] is not None else ('>= ' + lo + ' ' + unit))
            return {'Section': sec, 'Description': p['desc'], 'Nominal': limit_text.strip(), 'Tolerance -': lo, 'Tolerance +': hi, 'UOM': unit,
                    'As Found': rd, 'OOT': 'OOT' if failed else '', 'As Left': 'Same', 'Uncertainty': unc}
        row = report_pdf.cert_row(p['desc'], p['nominal'], p['low'] if p['low'] is not None else float('nan'), p['high'] if p['high'] is not None else float('nan'),
                                  p['unit'], r['reading'], failed, section=sec, uncertainty=unc)
        if p['low'] is None: row['Tolerance -'] = 'N/A'
        if p['high'] is None: row['Tolerance +'] = 'N/A'
        if p['low'] is None or p['high'] is None: row['Nominal'] = ('<= ' if p['high'] is not None else '>= ') + row['Tolerance +' if p['high'] is not None else 'Tolerance -'] + ' ' + row['UOM']
        return row

    def certificate_rows(self):
        """As Found for every recorded point; As Left where it was measured again after an adjustment, else 'Same'."""
        rows = []
        for p in POINTS:
            row = self.found_left_row(p, lambda r: self.certificate_row(p, r))
            if row: rows.append(row)
        return rows

    def export_pdf(self):
        rows = self.certificate_rows()
        if not rows: messagebox.showinfo('No results', 'No recorded results to export yet.'); return
        try: import report_pdf, report_dialog
        except ImportError as exc: messagebox.showerror('Report export', str(exc)); return
        details = report_dialog.ask_details(self.root, 'Tektronix MDO4000C performance verification')
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        c = self.cfg
        opts = ', '.join([x for x in (c.sa if c.sa != 'None' else '', 'AFG' if c.afg else '', 'DVM' if c.dvm else '', 'TPA-N-PRE attached' if c.tpa else '') if x]) or 'none'
        skipped = sum(1 for v in self.found.values() if v.get('result') == 'SKIP')
        note = ('Uncertainty: points without an input signal show N/A. Analog points use the laboratory A2LA scope (Fluke 5560A CMC); RF, function-generator and meter points '
                'use the entries in specs/mdo4000c_reference_cmc.json and show N/A where none is set.' + (f' {skipped} point(s) were skipped (instrument not available).' if skipped else ''))
        try:
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'Tektronix MDO{c.model}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Options', opts), ('Source', 'MDO4000C Specifications and Performance Verification, 077-1178-01 Rev B')],
                                             demo=demo, details=details, footer_note=note, title='Calibration Data')
        except ImportError:
            messagebox.showerror('PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            messagebox.showerror('PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV', '*.csv')], initialfile=f'MDO{self.cfg.model}_verification.csv')
        if not path: return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['Instrument ID', self.asset.get(), 'Serial', self.serial.get(), 'Config', json.dumps(self.cfg.as_dict())]); w.writerow([])
            w.writerow(['#', 'Section', 'Description', 'Low', 'High', 'Unit', 'Reading', 'Result', 'Uncertainty', 'Worksheet values', 'Timestamp', 'Synthetic', 'As Left', 'As Left result'])
            for p in self.active_points():
                r = self.found.get(str(p['id']), {}); lr = self.left.get(str(p['id']), {})
                w.writerow([p['id'], SECTION_TITLE[p['section']], p['desc'], p['low'], p['high'], p['unit'], r.get('reading', ''), r.get('result', ''), r.get('uncertainty', ''),
                            json.dumps(r.get('raw', {})), r.get('timestamp', ''), r.get('synthetic', ''), lr.get('reading', 'Same' if r else ''), lr.get('result', '')])
        self.status.set(f'Exported {path}')

    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_addrs(); self.disconnect(); self.root.destroy()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    App(root, demo='--demo' in argv)
    root.mainloop()
