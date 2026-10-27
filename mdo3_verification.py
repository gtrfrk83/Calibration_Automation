"""Tektronix 3 Series MDO (MDO32 / MDO34) performance verification, driven from the manufacturer's test record.

Test points and limits come from specs/tektronix_mdo3_pv.json (3 Series MDO Specifications and Performance Verification, 077-1499-10).
The technician selects the model (channels and bandwidth, e.g. 34-1000) and the installed options (3-SA3, 3-AFG, 3-DVM, TPA-N-PRE);
only the points that apply are listed and run.

Stimulus:   Fluke 5560A (SCOPE DCV / LEVSINE / MEASR / square) for the analog tests, Fluke 96270A for the RF tests, Agilent 33220A or
            33250A for the time mark and for the delta-time points the 5560A cannot make. The AFG tests read the oscilloscope's AFG with
            a SCPI DMM / counter (or typed readings).
Never run unattended: the program stops and asks for every cable, terminator or instrument change, and for every front-panel-only
step. Writes are never retried; all settings are read back; outputs go to standby / off after every point.

This is the 3 Series' own engine.  The run logic (Config, IO, Runner, App) is here; the pure helpers that do not depend on the model (spectrum
analysis, judging, the uncertainty text format) are imported from mdo4000c_verification, which this file never changes.  The few helpers that read
the spec, the reference-CMC file or the unit list of a family are repeated here (display_row, reference_cmc, uncertainty_parts / _text,
tar_tur_fields) so that they use the 3 Series' own.
"""
from __future__ import annotations

import json, math, queue, sys, threading, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import ui_port
import ui_theme_core as ui                   # only its toolkit-free helpers here (si_row, si, report_filename, Settings); the window code is in mdo4000c_view_qt.py
from ui_port import ui as port          # every dialog, variable, scheduler call and window operation goes through the UI port (ui_port.py)
import appdata
import datamode
import drivers
import procmods_engine
import reset_startup
import virtualbench
import hookups
from mdo4000c_verification import (Skip, Stopped, demo_reading, fmt_plain, format_uncertainty, judge, max_excluding, noise_floor_max,   # noqa: F401  shared pure helpers
                                   to_per_hz, trace_peak)

SPEC_PATH = HERE / 'specs' / 'tektronix_mdo3_pv.json'
REF_CMC_PATH = HERE / 'specs' / 'mdo3_reference_cmc.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
POINTS = SPEC['points']
SECTION_TITLE = {s['id']: s['title'] for s in SPEC['sections']}
SECTION_PAGE = {s['id']: s['page'] for s in SPEC['sections']}
MODELS = SPEC['models']
MODEL_INFO = SPEC['model_info']                # per model: channels, bandwidth_hz, bw_limits, counter_max_hz, option
PLAIN_UNITS = {'%', 'dB', 'dBm', 'dBc', 'dBm/Hz', 'dBc/Hz', 'ratio', '', 'div'}

FAMILY = dict(label='MDO3', settings='TektronixMDO3', panel='MDO3', default_model='34-1000', scope_addr='', hv_max=100.0, trig_out='AUX OUT',
              report_title='Tektronix 3 Series MDO performance verification',
              source='3 Series MDO Specifications and Performance Verification, 077-1499-10')
CAL_MODEL = '5560A'
FREQ_CMC_KINDS = ('DVMFREQ', 'AFGFREQ')       # frequency points: the lab's Frequency - Measure CMC (GPS-referenced) is their uncertainty
SLEEP_SCALE = 1.0            # tests set this to 0
VIRTUAL_PACE = 1.0           # a virtual-bench demo shortens the waits (virtualbench.WAIT_SCALE); 1.0 = real
PM_PAUSE_SCALE = 1.0         # a procedure modification (mdo.pause_scale) multiplies every wait; set by Runner.run_point, 1.0 = factory


def pause(seconds):
    if seconds > 0 and SLEEP_SCALE > 0:
        time.sleep(seconds * SLEEP_SCALE * PM_PAUSE_SCALE * VIRTUAL_PACE)


def set_virtual_pace(on):
    global VIRTUAL_PACE
    VIRTUAL_PACE = virtualbench.WAIT_SCALE if on else 1.0


# ======================================================================================================================
# which points apply
# ======================================================================================================================
class Config:
    def __init__(self, model='34-1000', sa='None', afg=False, dvm=False, tpa=False):
        self.model, self.sa, self.afg, self.dvm, self.tpa = model, sa, afg, dvm, tpa

    def as_dict(self):
        return dict(model=self.model, sa=self.sa, afg=self.afg, dvm=self.dvm, tpa=self.tpa)

    def applies(self, p):
        if p.get('models') and self.model not in p['models']:
            return False
        for token in p.get('req') or []:
            ok = {'AFG': self.afg, 'DVM': self.dvm, 'TPA': self.tpa, 'noTPA': not self.tpa,
                  'SA3': self.sa == 'SA3', 'noSA3': self.sa != 'SA3'}[token]          # SA3 / noSA3: option 3-SA3 (the 1 GHz analyzer is standard)
            if not ok:
                return False
        return True


# ======================================================================================================================
# display
# ======================================================================================================================
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


def uncertainty_parts(p, raw):
    """The number behind uncertainty_text: (value, unit, style) or None when the text is 'N/A'.  value is the unrounded uncertainty
    in `unit` ('ohm', '%', 'V', 'ratio' for the bandwidth gain, or the unit of the reference-file entry); style says how
    uncertainty_text prints it ('si' = uncertainty.format_value, 'bw' = plain 2 significant figures, 'ref' = number and unit)."""
    if (p['stim'] == 'none' and p['kind'] not in FREQ_CMC_KINDS) or p.get('passfail'):
        return None
    import report_pdf, uncertainty, uncertainty_budget
    sc = report_pdf.scope()
    k = p['kind']
    try:
        if k == 'ABSAMP':                  # RF level / flatness: the Fluke 96270A level accuracy over the sweep (standards sheet; the scope has no RF level CMC)
            b = uncertainty_budget.rf_level_sweep(p)
            if b is not None:
                return b.reported, 'dB', 'si'
        if sc is not None:
            if k == 'IMP':
                v, u, _ = sc.oscilloscope('impedance', ohms=p['nominal'])
                return (v, 'ohm', 'si') if v is not None else None
            if k == 'GAIN':
                # each applied level: the larger of the 5560A DC budget and the scope's oscilloscope DC CMC (absolute volts); the two are combined
                # in quadrature and shown as a percentage of the expected difference (CMC-only before: the budget is far below the CMC at every level)
                bs = [uncertainty_budget.osc_dc(p[n], p['term'], CAL_MODEL, sc) for n in ('vneg', 'vpos')]
                if all(b is not None and b.value for b in bs):
                    return 100 * math.hypot(*[b.value for b in bs]) / abs(p['vdiff']), '%', 'si'
            if k == 'OFFSET':
                b = uncertainty_budget.osc_dc(p['offset'], p['term'], CAL_MODEL, sc)
                return (b.value, 'V', 'si') if b is not None else None
            if k == 'BW':
                v, u, _ = sc.oscilloscope('bandwidth', volts_pp=p['vin_pp'], frequency=p['freq'])
                if v is not None:
                    ratio = 10 ** (v / 20) - 1
                    return ratio * max(raw.get("gain", raw.get("reading", 1)), 0.707), 'ratio', 'bw'
            if k == 'DVMDC':
                b = uncertainty_budget.osc_dc(p['nominal'], '1M', CAL_MODEL, sc)
                if b is not None:
                    return b.value, 'V', 'si'
    except Exception:
        return None
    ref = reference_cmc().get(k)
    if ref and (ref.get('rel') is not None or ref.get('abs') is not None):
        reading = abs(raw.get('reading', p['nominal']))
        value = (ref.get('rel') or 0) * reading + (ref.get('abs') or 0)
        if k in FREQ_CMC_KINDS and sc is not None and ref.get('unit', p['unit']) == 'Hz':
            floor = sc.dmm('FREQ', p['nominal'], None, None, basis='measure')     # never below the A2LA frequency CMC
            if floor is not None and value < floor:
                value = floor
        return value, ref.get('unit', p['unit']), 'ref'
    if k in FREQ_CMC_KINDS and sc is not None and p['unit'] == 'Hz':
        # a frequency read by the GPS-referenced lab standard (the 5560A frequency into the DVM counter; the AFG output on the lab counter): the lab's
        # 'Frequency - Measure' CMC (7.1e-12 of the frequency), on its own: the CMC is already the expanded figure, there is no divisor and no amplitude term
        try:
            v = sc.dmm('FREQ', p['nominal'], None, None, basis='measure')
        except Exception:
            v = None
        if v is not None:
            return v, 'Hz', 'si'
    return None


def uncertainty_text(p, raw):
    """Expanded uncertainty for a point, or 'N/A'. Points with no stimulus are always N/A; stimulus points use the lab's A2LA scope
    (5560A) or the editable reference table for the 96270A / function generator / reference meters; blank entries are N/A."""
    parts = uncertainty_parts(p, raw)
    if parts is None:
        return 'N/A'
    if parts[2] == 'ref':
        return format_uncertainty(parts)
    try:
        return format_uncertainty(parts)
    except Exception:
        return 'N/A'


def tar_tur_fields(p, r):
    """dict(TAR, TUR) strings for one recorded point (r = its record), used only when the report asks for them.
    TUR = tolerance / the uncertainty printed in the Uncertainty column, only when both are in the same unit and the printed text is
    the one uncertainty_parts() gives now (a stored text from another scope version gives a blank).  TAR only for the points the
    Fluke 5560A sources as DC volts (DC offset, DVM DC): its specmanager DCV row at that voltage, in volts; blank for every other test
    (gain is a %, the others are measurements or non-DC / leveled-sine / square stimulus with no matching specification row)."""
    import tartur
    try:
        if p.get('passfail') or (p.get('stim') == 'none' and p['kind'] not in FREQ_CMC_KINDS):
            return dict(TAR='', TUR='')
        raw = r.get('raw', {})
        text = r.get('uncertainty') or uncertainty_text(p, raw)
        parts = uncertainty_parts(p, raw)
        u = uu = None
        if parts is not None and text != 'N/A' and format_uncertainty(parts) == text:
            import uncertainty
            u, uu = uncertainty.round_up(parts[0]), parts[1]
        acc = au = None
        if p['kind'] == 'ABSAMP':
            import uncertainty_budget
            b = uncertainty_budget.rf_level_sweep(p)
            acc, au = (b.hit.limit, 'dB') if b is not None else (None, None)
        if p['kind'] in ('OFFSET', 'DVMDC') and p['stim'] == 'cal':
            acc, au = tartur.standard_accuracy('5560A', 'DCV', abs(p['offset'] if p['kind'] == 'OFFSET' else p['nominal']))
        return tartur.ratio_fields(tartur.from_values(tartur.half_width(p['low'], p['high']), p['unit'], acc, au, u, uu))
    except Exception:
        return dict(TAR='', TUR='')


# ======================================================================================================================
# bench I/O
# ======================================================================================================================
class IO(reset_startup.IOResetMixin, procmods_engine.ProcModsMixin):
    """Every instrument the procedure can use. Only the oscilloscope and the 5560A are required; the others are opened when an address is given."""

    def __init__(self, addrs, transports=None, mods=None, virtual=False):
        self.log = drivers.CommandLog()
        self.virtual = bool(virtual)
        if self.virtual: virtualbench.mark_log(self.log)
        self.addrs = addrs
        self.scope = self.cal = self.rf1 = self.rf2 = self.gen = self.dmm = self.counter = self.power = None
        t = transports or {}
        self._tr = t
        def tr(name, **kw):
            return t[name] if name in t else drivers.open_visa(to_visa(addrs[name]), timeout=30, **kw)
        try:
            self.scope = drivers.TektronixMDO3(tr('scope'), self.log, label=FAMILY['label']); self.scope.connect()
            self.cal = drivers.Fluke5560A(tr('cal', baud=int(addrs.get('cal_baud', 9600))), self.log, label='5560A')
            self.cal.open(verify_model=True); self.cal.clear_status()
            for key, cls, label in (('rf1', drivers.Fluke96270A, '96270A'), ('rf2', drivers.Fluke96270A, 'RF2'), ('gen', drivers.AgilentAFG, 'FuncGen'),
                                    ('dmm', drivers.ReferenceMeter, 'RefDMM'), ('counter', drivers.ReferenceMeter, 'Counter'), ('power', drivers.ReferenceMeter, 'PowerMeter')):
                if key in t or addrs.get(key, '').strip():
                    inst = cls(tr(key), self.log, label=label); inst.connect(); setattr(self, key, inst)
            self.pm_attach(mods, *self.pm_drivers())
        except Exception:
            self.close(); raise
        self.ident = self.scope.idn

    def reset_roles(self):
        return [d for d in (self.cal, self.rf1, self.rf2, self.gen, self.dmm, self.counter, self.power) if d is not None], [self.scope]

    def pm_drivers(self):
        return tuple(d for d in (self.scope, self.cal, self.rf1, self.rf2, self.gen, self.dmm, self.counter, self.power) if d is not None)

    def reconnect_scope(self, attempts=None, wait=None):
        """Re-open the oscilloscope after the power cycle the self test requires."""
        attempts = self.pm_param('mdo.reconnect_attempts', 36) if attempts is None else attempts
        wait = self.pm_param('mdo.reconnect_wait', 5.0) if wait is None else wait
        self.scope.close()
        for _ in range(attempts):
            try:
                t = self._tr['scope'] if 'scope' in self._tr else drivers.open_visa(to_visa(self.addrs['scope']), timeout=30)
                self.scope = drivers.TektronixMDO3(t, self.log, label=FAMILY['label']); self.scope.connect()
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
        if virtualbench.log_is_virtual(self.log): return          # a virtual (demo) session is never evidence
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  {FAMILY["label"]} session\n' + '\n'.join(self.log.lines()) + '\n')
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
    @procmods_engine.point_commands(io_of=lambda runner: runner.io)
    def run_point(self, p):
        global PM_PAUSE_SCALE
        PM_PAUSE_SCALE = self.io.pm_param('mdo.pause_scale', 1.0)       # procedure modification; 1.0 unless one is stored
        info = MODEL_INFO.get(self.cfg.model)                            # the model's flags: the driver checks the FULl bandwidth read-back against bandwidth_hz
        if info:
            self.io.scope.full_bw_hz = info['bandwidth_hz']              # the 3 Series driver checks the FULl bandwidth read-back against it
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
        if p.get('per_div'):                                # the 3 Series test record prints DC balance in divisions (mean / V/div, PV p. 92 step 16)
            v = self.io.scope.mean_of(ch)
            return v / p['vscale'], dict(mean_volts=v)
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
        self.dc_setup(ch, p['term'], p['bw'], p['vscale'], offset=p['offset'], hscale=p.get('hscale', 1e-3))
        self.dc_source(p['term'])
        if abs(p['offset']) >= 50 and self._wired_hv != (ch, p['term']):
            self.ask('HIGH VOLTAGE', f'{abs(p["offset"]):g} V DC output', [('Safety', f'The next points apply up to {FAMILY["hv_max"]:g} V DC. Check the cable and connector are rated, keep clear of the connection, and never touch the BNC while the output is on.')],
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
        s.timebase(p.get('ref_hscale', 1e-3))                # step 9: the reference reading at 1 ms/div
        s.measure_setup('PK2pk', f'CH{ch}')
        s.stats_reset(weighting=16); pause(3.0)
        vin = s.stat_mean()                                  # Vin-pp at the 10 MHz reference frequency (step 11)
        s.timebase(p['hscale'])                              # step 13: 4 ns/div for the bandwidth reading
        cal.set_levsine(p['vin_pp'], p['freq']); cal.check_error('levsine at bandwidth'); pause(2.0)
        s.stats_reset(weighting=16); pause(3.0)
        vbw = s.stat_mean()                                  # Vbw-pp at the bandwidth frequency
        cal.standby_quiet()
        gain = vbw / vin                                     # Gain = Vbw-pp / Vin-pp (must be >= 0.707)
        return gain, dict(vin_pp=vin, vbw_pp=vbw, gain=gain)

    # ---- random noise -----------------------------------------------------------------------------------------------------------------
    def do_noise(self, p):
        if p.get('method') == 'rms_mean':
            return self.noise_rms_mean(p)
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

    def noise_rms_mean(self, p):
        """3 Series method (PV manual p. 104): sample mode, the point's time base, RMS and Mean measured together, RMS noise = sqrt(RMS^2 - Mean^2)."""
        ch = p['ch']
        self.wire(('NOISE', ch), f'Random noise - CH{ch}', [('Disconnect', 'Disconnect everything from the oscilloscope inputs. Leave the inputs open.')])
        s = self.io.scope
        self.fresh_scope(('NOISE', ch))
        s.select_only(ch)
        s.channel(ch, term=p['term'], bw=p['bw'], vscale=p['vscale'], offset=0.0, position=0.0)
        s.timebase(p.get('hscale', 10e-3))
        s.acquire_mode('SAMple')
        s.gating_off()
        s.measure_setup('RMS', f'CH{ch}', slot=1)
        s.measure_setup('MEAN', f'CH{ch}', slot=2)
        s.stats_reset(weighting=64); pause(4.0)
        rms, mean = s.stat_mean(1), s.stat_mean(2)
        return math.sqrt(max(rms * rms - mean * mean, 0.0)), dict(rms=rms, mean=mean)

    # ---- reference frequency ---------------------------------------------------------------------------------------------------
    def need(self, inst, name):
        if inst is None:
            raise Skip(f'{name} is not configured')
        return inst

    def do_reffreq(self, p):
        gen = self.need(self.io.gen, 'the function generator (33220A / 33250A)')
        vpp, fine = p.get('vpp', 2.0), p.get('fine_hscale', 200e-9)
        self.wire(('REF',), 'Reference frequency error', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Function generator output to CH1 with a 50 Ω cable (the program sets a {1.0 / p["period"]:g} Hz square wave = {p["period"] * 1e3:g} ms mark period, {vpp:g} V p-p).'),
                  ('Accuracy', 'The generator time base must be at least 4x better than the limit. Lock it to a 10 MHz reference if it is not already.')])
        s = self.io.scope
        self.fresh_scope(('REF',))
        gen.square(1.0 / p['period'], vpp)
        s.select_only(1)
        s.channel(1, term='50', vscale=0.5, offset=0.0, position=0.0)
        s.timebase(p.get('coarse_hscale', 20e-3))
        s.trigger_edge('CH1', level=0.0, mode='NORMal')
        gen.output(True); pause(2.0)
        s.delay(p['period'])
        s.timebase(fine)
        pause(2.0)
        edge = s.edge_time(1)
        gen.output(False)
        if p.get('per_div'):                                 # the 3 Series record prints the deviation in divisions of the fine time base (PV p. 103)
            return (edge - p['period']) / fine, dict(edge_time=edge, deviation_s=edge - p['period'])
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

    def square_source(self, ch, freq, vpp, label):
        """The time-mark square wave (fast rising edge) of the DVM frequency test (PV p. 130 step 3), 50 Ω source into the 50 Ω input, from the function
        generator (33220A / 33250A, APPLy:SQUare).  The 5560A's SCOPE SQUARE / MARKER commands are not verified, so it is not used for the square wave."""
        gen = self.io.gen
        if gen is None:
            raise Skip('the time-mark square wave needs the function generator (33220A / 33250A); none is configured')
        self.source_wire('GEN', ch, label)
        try:
            gen.square(freq, vpp)
            gen.output(True)
        except drivers.InstrumentError as exc:
            self.io.all_outputs_off(); self._wired = None
            raise Skip(f'GEN: {exc}')
        pause(2.0)
        return 'GEN'

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
        sd = s.delay_stddev(ch, samples=100, wait=self.io.pm_param('mdo.delta_wait', 8.0))
        return sd, dict(source=src)

    # ---- RF -------------------------------------------------------------------------------------------------------------------------------
    def rf_out(self, inst, f, level):
        inst.set_rf(f, level)
        inst.output(True)

    def do_danl(self, p):
        label = 'TPA-N-PRE input' if p.get('tpa') else 'RF input'
        self.wire(('DANL', bool(p.get('tpa'))), f'DANL - {label}', [('Terminate', f'Fit a 50 Ω N terminator on the {label} and make sure no signal is applied.')]
                  + ([('TPA-N-PRE', 'Push Menu on the TPA-N-PRE; on the oscilloscope set Mode to Auto.')] if p.get('tpa') else []))
        s = self.io.scope
        det = {'detection': p['detection']} if p.get('detection') else {}      # average detection (PV p. 110)
        s.rf_setup(start=p['f_start'], stop=p['f_stop'], ref_level=p['ref_level'], averages=32, **det)
        pause(60.0 if p['f_start'] < 50e3 else 20.0)
        xs, ys = s.rf_trace(True)
        f_pk, l_pk = noise_floor_max(xs, ys)
        if p.get('center'):                                   # the manual then sets a fixed centre frequency and a 10 MHz span (pp. 111-112, 120-121) and records the highest noise there
            s.rf_setup(center=p['center'], span=p.get('span', 10e6), ref_level=p['ref_level'], averages=32, **det)
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

    def do_spur(self, p):
        self.wire(('SPUR',), 'Residual spurious response', [('Terminate', 'Fit a 50 Ω N terminator on the RF input and make sure no signal is applied.')])
        s = self.io.scope
        s.rf_setup(start=p['f_start'] if not p['at_freq'] else p['at_freq'] - 5e6, stop=p['f_stop'] if not p['at_freq'] else p['at_freq'] + 5e6,
                   rbw=p['rbw'], ref_level=p.get('ref_level', -25.0), averages=32)
        pause(60.0 if p['f_start'] < 50e3 else 30.0)
        xs, ys = s.rf_trace(True)
        if p['at_freq']:
            _f, lvl = trace_peak(xs, ys, p['at_freq'], 1e6)
        else:
            best = max_excluding(xs, ys, p['exclude'], 1e6)
            _f, lvl = best
        return lvl, dict(at_hz=_f)

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
        self.wire(('TRIG',), 'Trigger output', [('Disconnect', 'Remove other cables.'), ('Connect', f'Rear-panel {FAMILY["trig_out"]} to CH1 with a 50 Ω BNC cable.')])
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
        s.channel(ch, term='50', vscale=p.get('vscale', 0.5), offset=0.0, position=0.0)
        s.timebase(p.get('hscale', 20e-3))
        s.trigger_edge(f'CH{ch}', mode='AUTO')
        counter = p.get('counter') == 'trigger'             # 3 Series: the trigger frequency counter (PV p. 130), not the DVM frequency mode
        if counter:
            s.trigger_counter_on()
        else:
            s.dvm('FREQuency', ch)
        if p.get('waveform') == 'square':
            src = self.square_source(ch, p['freq'], p.get('vpp', 1.0), 'DVM frequency (time mark)')
        else:
            src = self.sine_source(ch, p['freq'], p.get('vpp', 1.0), 'DVM frequency')
        v = s.trigger_frequency() if counter else s.dvm_frequency()
        return v, dict(source=src, waveform=p.get('waveform', 'sine'))


# ======================================================================================================================
# the application window
# ======================================================================================================================
class App(virtualbench.VirtualMixin, reset_startup.AppResetMixin, datamode.DataModeMixin, procmods_engine.ProcModsMixin):
    def __init__(self, root, demo=False, fast_demo=False):
        self.root, self.demo = root, demo
        self.init_virtual(demo, fast_demo)
        self.io = None
        self._busy = False
        self.stop = False
        self.results = {}
        self.q = queue.Queue()
        self.cfg = Config()
        self.pm_init('mdo', FAMILY['label'], demo=demo, lists=[POINTS], shape='band')    # procedure modifications: saved overrides for this model
        self.ui_view.setup_window(self)
        self.settings = ui.Settings(FAMILY['settings'])
        g = self.settings.get
        self.asset, self.serial = port.var(), port.var()
        self.v_model = port.var(g('model', FAMILY['default_model']))
        self.v_sa = port.var(g('sa', 'None'))
        self.v_afg = port.var(g('afg', 'False') == 'True', 'bool')
        self.v_dvm = port.var(g('dvm', 'False') == 'True', 'bool')
        self.v_tpa = port.var(g('tpa', 'False') == 'True', 'bool')
        self.addr = {k: port.var(g(k, d)) for k, d in (
            ('scope', FAMILY['scope_addr']), ('cal', 'COM9'), ('cal_baud', '9600'), ('rf1', ''), ('rf2', ''), ('gen', ''), ('dmm', ''), ('counter', ''), ('power', ''))}
        self.status = port.var()
        self.detail = port.var('Select a test point to see its setup.')
        self.show_section = port.var('All sections')
        self.show_status = port.var('All points')
        self._build_ui()
        self.on_config(save=False)
        self.status.set(virtualbench.status_text(self) if demo else
                        'Step 1: instrument ID and model/options. Step 2: addresses, then Test Connections. Step 3: Run All Pending.')
        port.on_close(root, self.on_close)
        port.bind_key(root, '<Control-s>', self.save)
        self.ui_view.finish_window(self)
        port.after(self.root, 50, self._pump)

    # ---- selection ---------------------------------------------------------------------------------------------------
    def read_cfg(self):
        self.cfg = Config(self.v_model.get(), self.v_sa.get(), self.v_afg.get(), self.v_dvm.get(), self.v_tpa.get())
        if self.cfg.model == '4024C' and False:
            pass
        return self.cfg

    def active_points(self):
        return [p for p in POINTS if self.cfg.applies(p) and not p.get('skip')]

    @property
    def busy(self): return self._busy
    @busy.setter
    def busy(self, v):
        self._busy = v
        if hasattr(self, 'btn_run'): self._sync_buttons()

    def _sync_buttons(self): self.ui_view.sync_buttons(self)

    # ---- layout -------------------------------------------------------------------------------------------------------------
    VIEW = 'mdo3_view'                              # window code: mdo3_view_qt.py

    @property
    def ui_view(self): return port.view(self.VIEW)

    def _build_ui(self): self.ui_view.build_ui(self)

    # ---- configuration changed -------------------------------------------------------------------------------------------------
    def on_config(self, save=True):
        self.v_model.set(self.v_model.get().replace('MDO', ''))
        self.read_cfg()
        if save:
            for k, v in (('model', self.v_model.get()), ('sa', self.v_sa.get()), ('afg', str(self.v_afg.get())), ('dvm', str(self.v_dvm.get())),
                         ('tpa', str(self.v_tpa.get()))):
                self.settings.set(k, v)
            self.settings.save()
        self.refresh()

    def read_options(self):
        if self.fast_demo:
            port.message('info', 'Demo mode', 'Demo mode uses no hardware.'); return
        if self.io is None: self.test_connections()
        if self.io is None: return
        opts = self.io.scope.installed_options()
        model = self.io.scope.model
        if model in MODELS: self.v_model.set(model)
        elif model and f"{model}-{self.v_model.get().split('-')[-1]}" in MODELS:     # 3 Series: the reply names MDO32 / MDO34; the bandwidth option stays as chosen
            self.v_model.set(f"{model}-{self.v_model.get().split('-')[-1]}")
        self.v_sa.set('SA3' if 'SA3' in opts else 'None')
        self.v_afg.set('AFG' in opts); self.v_dvm.set('DVM' in opts)
        self.on_config()
        port.message('info', 'Options read', f'Model MDO{model}; options reported: {", ".join(sorted(opts)) or "none"}.\nCheck the boxes against the instrument label and correct anything the scope does not report.')

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

    def pm_driver_classes(self):
        return (drivers.TektronixMDO3, drivers.Fluke5560A, drivers.Fluke96270A, drivers.AgilentAFG, drivers.ReferenceMeter)

    def sim_bench(self):
        """(bench, transports) of the simulated bench (demo / virtual bench and the procedure-editor dry run)."""
        from drivers.simulated_mdo3 import make_mdo3_bench
        return make_mdo3_bench(self.cfg.model)

    def pm_point_fields(self, view):
        out = super().pm_point_fields(view)
        out['nominal']['note'] = ('The nominal is only the value the reading is judged against; the signals this procedure sources are set '
                                  'from the point\'s own settings, which this window does not change.')
        return out

    def pm_plan_point(self, p):
        """The commands Runner.run_point sends for point p: a dry run on the simulated bench (procmods_plan).  The prompts of the point ask the
        scripted answer 'yes' and typed readings answer the point's nominal; optional instruments are present when they have an address (all of
        them when none has: the plan then assumes the full bench)."""
        import procmods_plan
        addrs = self.addrs()
        optional = ('rf1', 'rf2', 'gen', 'dmm', 'counter', 'power')
        have = [k for k in optional if (addrs.get(k) or '').strip()]

        def build(mods):
            _bench, t = self.sim_bench()
            if have:
                t = {k: v for k, v in t.items() if k not in optional or k in have}
            return IO(dict(cal_baud=int(addrs.get('cal_baud') or 9600)), transports=t, mods=mods)

        class PlanApp:
            stop = False

            def __init__(s, io):
                s.io, s.cfg = io, self.cfg

            def request(s, kind, payload=None):
                return payload['p']['nominal'] if kind == 'manual' else True

            def post(s, *a, **k):
                pass
        global PM_PAUSE_SCALE
        keep = PM_PAUSE_SCALE                              # run_point sets this module-level wait scale: put it back, a run may be using it
        try:
            return procmods_plan.run_plan(self.pm_state, build, lambda io: Runner(PlanApp(io)).run_point(p))
        finally:
            PM_PAUSE_SCALE = keep

    def pm_refresh_view(self):
        self.post('refresh')                                  # called from the worker thread: the table is rebuilt on the main thread

    def pm_show_note(self, p):
        """The worker thread cannot open a window: ask the main thread (the same 'ask' the procedure's own prompts use)."""
        try:
            self.request('ask', dict(title=f'Note for point {p["id"]}', heading=p['desc'], steps=[('Note', str(p.get('tech_note')))],
                                     facts=[('Point', str(p['id']))], caution=None, ok='OK'))
        except Stopped:
            raise
        except Exception:
            pass

    def refresh(self):
        keep = self.ui_view.table_selection(self)
        self.ui_view.table_set_rows(self, ((str(p['id']), *self._row(p)) for p in POINTS if self._visible(p)), keep)
        self.update_summary()

    def _update_row(self, p):
        iid = str(p['id'])
        if self.ui_view.table_has(self, iid):
            v, tags = self._row(p); self.ui_view.table_update_row(self, iid, v, tags)
        self.update_summary()

    def update_summary(self):
        self.update_shell_progress(self.active_points())
        self.update_shell_sections(self.active_points(), lambda p: SECTION_TITLE[p['section']])

    def on_select(self, _e=None):
        sel = self.ui_view.table_selection(self)
        if not sel: return
        p = POINTS[int(sel[0]) - 1]
        nom, lo, hi, _r, unit = display_row(p)
        rec = self.results.get(str(p['id']), {})
        raw = rec.get('raw')
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        stim = {'none': 'no input signal', 'cal': 'Fluke 5560A', 'rf': 'Fluke 96270A', 'rf2': 'two RF sources', 'gen': 'function generator'}[p['stim']]
        work = ('\nWorksheet: ' + ', '.join(f'{k} = {v:.6g}' if isinstance(v, float) else f'{k} = {v}' for k, v in raw.items())) if raw else ''
        both = ('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''
        self.detail.set(f'{p["desc"]}\nStimulus: {stim}  |  Manual page {SECTION_PAGE[p["section"]]}{extra}{work}{both}')

    # ---- connections ----------------------------------------------------------------------------------------------------------------
    def find_instruments(self):
        try:
            import pyvisa
            found = list(pyvisa.ResourceManager().list_resources())
        except Exception as exc:
            self.status.set(f'Instrument search needs pyvisa and a VISA backend ({exc}). You can still type an address.'); return
        self.ui_view.set_choices(self, found)
        self.status.set(f'{len(found)} VISA resource(s): ' + (', '.join(found) if found else 'none'))

    def addrs(self):
        return {k: v.get() for k, v in self.addr.items()}

    def test_connections(self):
        if self.fast_demo: port.message('info', 'Demo mode', 'Demo mode uses no hardware.'); return
        self.status.set('Connecting ...'); port.flush(self.root)
        try:
            self.disconnect()
            if self.virtual:          # demo: the real IO / driver code over the simulated 3 Series bench (scope, 5560A, 96270A x2, generator, DMM, counter)
                self._vb, t = self.sim_bench()
                set_virtual_pace(True)
                self.io = IO(self.addrs(), transports=t, mods=self.pm_state, virtual=True)
            else: self.io = IO(self.addrs(), mods=self.pm_state)
        except Exception as exc:
            self.disconnect(); self._set_conn(False)
            self.status.set('Connection error: ' + str(exc)); port.message('error', 'Connection error', str(exc)); return
        self._set_conn(True)
        if not self.demo: self._save_addrs()
        used = [n for n, o in (('96270A', self.io.rf1), ('RF source 2', self.io.rf2), ('function generator', self.io.gen), ('reference DMM', self.io.dmm), ('counter', self.io.counter), ('power meter', self.io.power)) if o]
        tag = ' ' + virtualbench.VIRTUAL_TAG if self.virtual else ''
        self.status.set('Connected: ' + self.io.ident + tag + '. Outputs are OFF.')
        port.message('info', 'Connected' + (' (DEMO)' if self.virtual else ''), f'Oscilloscope: {self.io.ident}\nFluke 5560A: {self.io.cal.idn}\nAlso connected: {", ".join(used) or "no other instruments"}\nAll outputs are off.{tag}')

    def disconnect(self):
        if self.io: self.io.close(); self.io = None
        set_virtual_pace(False)
        self._set_conn(None)

    def _set_conn(self, ok):
        if hasattr(self, 'conn_pill'):
            self.conn_pill.set(self.chip_text() if self.virtual else 'Connected' if ok else 'Connection failed' if ok is False else ('Demo - no hardware' if self.demo else 'Not connected'),
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
                elif kind == 'select':
                    if self.ui_view.table_has(self, payload): self.ui_view.table_select(self, payload, see=True)
                elif kind == 'row': self._update_row(POINTS[payload - 1])
                elif kind == 'refresh': self.refresh()
                elif kind == 'done': self._finished(payload)
                elif kind == 'ask':
                    ok = port.operator_prompt(payload['title'], payload['heading'], payload['steps'], facts=payload['facts'], caution=payload['caution'], ok=payload['ok'], image=hookups.panel_image(FAMILY['panel']), parent=self.root)
                    if ok and self.virtual: virtualbench.mdo_operator_confirmed(self._vb, payload['title'])      # the virtual operator pushes the front-panel button
                    box['value'] = ok; box['ev'].set()
                elif kind == 'manual':
                    box['value'] = self._manual_dialog(payload); box['ev'].set()
                elif kind == 'reconnect_scope':
                    box['value'] = self._reconnect(); box['ev'].set()
        except queue.Empty:
            pass
        port.after(self.root, 50, self._pump)

    def _manual_dialog(self, req):
        while True:
            hint, start = '', None
            if self.virtual:       # demo: the same window; the box holds a plausible simulated reading, which may be replaced
                q = req.get('p') or {}
                if q.get('low') is not None and q.get('high') is not None:
                    start = virtualbench.plausible_text(q['low'], q['high'], q.get('id', 0), self.virtual_failures())
                elif q.get('nominal') is not None:
                    start = f"{q['nominal']:g}"
                hint = '\nDEMO: the box holds a simulated reading; type your own if you like.'
            text = port.ask_text('Enter reading' + (' [DEMO]' if self.virtual else ''), req['prompt'] + f'\n(value in {req["unit"]}, plain number)' + hint, parent=self.root, initial=start)
            if text is None: return None
            try: return float(text.replace(',', ''))
            except ValueError: port.message('warning', 'Reading', 'Enter a number.')

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
        sel = self.ui_view.table_selection(self)
        if sel: self.execute([POINTS[int(sel[0]) - 1]])
        else: port.message('info', 'Selection', 'Select a test point first.')

    def rerun_from(self):
        sel = self.ui_view.table_selection(self)
        if sel: self.execute(self.points_from(POINTS, sel[0]))
        else: port.message('info', 'Selection', 'Select a test point first.')

    def execute(self, points):
        if not self.confirm_found_overwrite(points): return
        if self.busy or not points: return
        if not self.asset.get().strip(): port.message('warning', 'Instrument ID', 'Enter an instrument ID.'); return
        points = self.pm_begin_run(points, self.asset.get().strip())   # load the saved modifications for this asset (patches POINTS)
        if not points: self.status.set('Every selected point is skipped by a procedure modification.'); return
        self.read_cfg()
        if self.fast_demo:
            for p in points:
                self._record(p, demo_reading(p), {}, True)
            self.status.set('Demo run complete.'); self.save(silent=True); return
        if self.io is None: self.test_connections()
        if self.io is None: return
        self.stop = False; self.busy = True
        if not self.reset_notice_ok(): return                  # unit-under-test notice, before any instrument is touched
        threading.Thread(target=self._worker, args=(points,), daemon=True).start()

    def _worker(self, points):
        runner = Runner(self)
        error = None
        try:
            self.post('status', 'Resetting instruments to default settings ...')
            self.reset_run()                               # every run (first, re-run, resume): before the first point; a failure ends the run here
            i = 0
            while i < len(points):
                if self.stop: raise Stopped()
                p, _previous = self.pm_step(points, i, None)      # live edits: applied here, between two points (procmods_live); LiveApplyError ends the run
                i += 1
                if p is None: continue                              # skipped by an edit made during the run
                self.post('status', f'Running {i}/{len(points)}: {p["desc"]}')
                self.post('select', str(p['id']))                       # the highlighted row follows the point being tested
                try:
                    reading, raw = runner.run_point(p)
                    self._record_threadsafe(p, reading, raw, bool(self.demo))
                except Skip as s:
                    self.results[str(p['id'])] = dict(result='SKIP', reason=str(s), synthetic=bool(self.demo), timestamp=datetime.now().isoformat(timespec='seconds'))
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
            self.status.set('Error - run stopped: ' + str(error)); port.message('error', 'Measurement stopped', str(error))
        else: self.status.set('Run complete. Save progress or export a report.')

    def _record_threadsafe(self, p, reading, raw, synthetic):
        raw = dict(raw, reading=reading)
        self.results[str(p['id'])] = dict(reading=reading, raw=raw, result=judge(p, reading), synthetic=synthetic,
                                          uncertainty=uncertainty_text(p, raw), timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label,
                                          **self.pm_result_fields())
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
        path.write_text(json.dumps(dict(asset=self.asset.get(), serial=self.serial.get(), demo=self.demo, config=self.cfg.as_dict(), **self.save_fields(), **self.pm_checkpoint_fields()), indent=2))
        if not silent: self.status.set(f'Saved {path.name}')

    def load(self):
        path = port.choose_file(filetypes=[('Checkpoint', '*.json')])
        if not path: return
        data = json.loads(Path(path).read_text())
        if self.file_has_synthetic(data) and not self.demo:
            if not port.ask_yes_no('Synthetic data', 'The checkpoint contains DEMO results. Load for review only?'): return
        self.asset.set(data.get('asset', '')); self.serial.set(data.get('serial', ''))
        c = data.get('config', {})
        self.v_model.set(c.get('model', self.v_model.get())); self.v_sa.set(c.get('sa', 'None'))
        for var, key in ((self.v_afg, 'afg'), (self.v_dvm, 'dvm'), (self.v_tpa, 'tpa')): var.set(bool(c.get(key, var.get())))
        self.load_results(data)
        self.pm_on_checkpoint(data)                                  # a saved modification snapshot is used unless the store has changed
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
        return [row for _p, row in self.certificate_pairs()]

    def certificate_pairs(self):
        """(point, report row) in the order certificate_rows() lists them."""
        pairs = []
        for p in POINTS:
            row = self.found_left_row(p, lambda r: self.certificate_row(p, r))
            if row: pairs.append((p, row))
        return pairs

    def tar_tur_for(self, p):
        """TAR / TUR strings of one point (the As Found record when it was measured, else the As Left one); only called when the report shows them."""
        key = str(p['id'])
        r = self.found.get(key)
        if not r or r.get('result') not in ('PASS', 'FAIL'):
            r = self.left.get(key) or {}
        if r.get('result') not in ('PASS', 'FAIL'):
            return dict(TAR='', TUR='')
        return tar_tur_fields(p, r)

    def export_pdf(self):
        pairs = self.certificate_pairs()
        rows = [row for _p, row in pairs]
        if not rows: port.message('info', 'No results', 'No recorded results to export yet.'); return
        try: import report_pdf
        except ImportError as exc: port.message('error', 'Report export', str(exc)); return
        details = port.report_details(FAMILY['report_title'], parent=self.root)
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = port.save_file(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        c = self.cfg
        opts = ', '.join([x for x in (c.sa if c.sa != 'None' else '', 'AFG' if c.afg else '', 'DVM' if c.dvm else '', 'TPA-N-PRE attached' if c.tpa else '') if x]) or 'none'
        skipped = sum(1 for v in self.found.values() if v.get('result') == 'SKIP')
        note = ('Uncertainty: points without an input signal show N/A. DC gain, DC offset and DVM DC points report the larger of the laboratory A2LA oscilloscope CMC and the budget '
                'built from the published DC voltage specification of the Fluke 5560A (divided by its coverage divisor, k = 2), rounded up; input impedance and bandwidth use the laboratory '
                'A2LA scope (CMC only); RF, function-generator and meter points '
                f'use the entries in specs/{REF_CMC_PATH.name} and show N/A where none is set.' + (f' {skipped} point(s) were skipped (instrument not available).' if skipped else ''))
        try:
            if report_pdf.details_tar_tur(details):
                rows = report_pdf.apply_tar_tur(rows, report_pdf.details_tar_tur(details), [self.tar_tur_for(p) for p, _row in pairs])
            instrument = f'Tektronix {MODEL_INFO[c.model]["title"]}' if c.model in MODEL_INFO else f'Tektronix MDO{c.model}'
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', instrument), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Options', opts), ('Source', FAMILY['source'])],
                                             demo=demo, details=details, footer_note=note, title='Calibration Data',
                                             snapshot_context=report_pdf.context_for(self))
        except ImportError:
            port.message('error', 'PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            port.message('error', 'PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not port.ask_yes_no('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_addrs(); self.disconnect(); port.close(self.root)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, demo=demo, fast_demo=fast)
    port.run_app(build)
