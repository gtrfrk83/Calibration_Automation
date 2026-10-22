"""Tektronix TDS2000C / TDS1000C-EDU performance verification, driven from the manufacturer's Chapter 4 (Service Manual 077-0446-01).

Test points and limits come from specs/tektronix_tds2000c_pv.json (built by specs/build_tds2000c_spec.py from the page images).
The sections run in the manual's order: self test, self calibration, DC gain, bandwidth, sample rate / delay time, edge trigger,
external edge trigger.

Stimulus: ONE instrument, the scope option of a Fluke 5560A, 5522A or 5520A (SCOPE DC volts, leveled sine, time marker). It replaces the
manual's DC source, leveled sine generator and time-mark generator.  The oscilloscope is on USB.

Never run unattended: the program stops and asks for every cable, terminator and splitter change.  Writes are never retried; settings are
read back; the calibrator is put in STANDBY (and that is confirmed) after every point.
Demo (no hardware):  python Procedures/Tektronix_TDS2000C_Verification.py --demo
"""
from __future__ import annotations

import json, math, queue, sys, threading, time, tkinter as tk
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

SPEC_PATH = HERE / 'specs' / 'tektronix_tds2000c_pv.json'
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8'))
POINTS = SPEC['points']
MODELS = SPEC['models']
MODEL_INFO = SPEC['models_info']
SECTION_TITLE = {s['id']: s['title'] for s in SPEC['sections']}
SECTION_PAGE = {s['id']: s['page'] for s in SPEC['sections']}
PLAIN_UNITS = {'', 'div'}
SLEEP_SCALE = 1.0            # tests set this to 0
CAL_CHOICES = ['Fluke 5560A', 'Fluke 5522A', 'Fluke 5520A']
SOURCE_LIMITS = dict(vpp_max=5.5, f_min=50e3)       # leveled-sine range used by the procedure (edit if your scope option differs)
STABLE_JITTER_PERIODS = 0.2   # edge-position spread (fraction of a period) above which the trigger is judged unstable (engine criterion)
STABLE_MIN_ACQ = 5            # acquisitions that must complete in the 1 s observation window with the trigger in Normal mode
STABLE_CAPTURES = 8
DIAGRAMS = HERE / 'diagrams'


def pause(seconds):
    if seconds > 0 and SLEEP_SCALE > 0:
        time.sleep(seconds * SLEEP_SCALE)


class Stopped(Exception):
    """The technician cancelled a prompt or pressed Stop."""


class Skip(Exception):
    """The point cannot be made with the configured instruments (reason shown to the technician)."""


# ======================================================================================================================
# which points apply
# ======================================================================================================================
class Config:
    def __init__(self, model='2024C'):
        self.model = model

    def as_dict(self):
        return dict(model=self.model)

    @property
    def info(self):
        return MODEL_INFO[self.model]

    def applies(self, p):
        return not p.get('models') or self.model in p['models']


# ======================================================================================================================
# pure helpers
# ======================================================================================================================
def judge(p, reading):
    if p.get('passfail'):
        return 'PASS' if reading >= 0.5 else 'FAIL'
    r = float(f'{reading:.9g}')
    lo, hi = p['low'], p['high']
    if lo is not None and r < float(f'{lo:.9g}'): return 'FAIL'
    if hi is not None and r > float(f'{hi:.9g}'): return 'FAIL'
    return 'PASS'


def display_row(p, reading=None):
    """(nominal, low, high, reading, unit) display strings. SI units share a prefix; divisions stay plain."""
    lo, hi, nom, unit = p['low'], p['high'], p['nominal'], p['unit']
    if p.get('passfail'):
        return ('Pass', 'Pass', 'Pass', '' if reading is None else ('Pass' if reading >= 0.5 else 'Fail'), '')
    if unit in PLAIN_UNITS:
        f = lambda v: 'N/A' if v is None else f'{v:.4g}'
        return (f(nom), f(lo), f(hi), '' if reading is None else f'{reading:.4g}', unit)
    nums = [nom] + [x for x in (lo, hi) if x is not None]
    vals, reads, unit_text = ui.si_row(nums, unit, [] if reading is None else [reading])
    it = iter(vals[1:])
    lo_t = next(it) if lo is not None else 'N/A'
    hi_t = next(it) if hi is not None else 'N/A'
    return (vals[0], lo_t, hi_t, reads[0] if reads else '', unit_text)


def fmt_plain(v, sig=4):
    return 'N/A' if v is None else f'{v:.{sig}g}'


def demo_reading(p):
    """Deterministic synthetic reading. Everything made from it is labelled demo data (never evidence)."""
    s = math.sin(p['id'] * 1.713)
    lo, hi, nom = p['low'], p['high'], p['nominal']
    if p.get('passfail'):
        return 1.0
    if lo is not None and hi is not None:
        return (lo + hi) / 2 + 0.38 * (hi - lo) / 2 * s
    return lo + (0.15 * abs(lo) if lo else 0.012) * (1 + 0.3 * s)


def edge_times(times, volts, slope, level=None):
    """Interpolated times at which the waveform crosses `level` (default: mid-level between its extremes) in the given direction."""
    lo, hi = min(volts), max(volts)
    if level is None:
        level = (lo + hi) / 2
    rising = slope.upper().startswith('RIS')
    out = []
    for i in range(1, len(volts)):
        a, b = volts[i - 1] - level, volts[i] - level
        if (rising and a < 0 <= b) or (not rising and a > 0 >= b):
            frac = a / (a - b) if a != b else 0.0
            out.append(times[i - 1] + frac * (times[i] - times[i - 1]))
    return out


def parse_out_reply(reply):
    """(amplitude V, frequency Hz) from a calibrator OUT? reply. 5520A: amp, unit, amp2, unit2, freq. 5560A style: amp, unit, freq, unit.
    Anything else raises, so an unexpected format is seen on the first bench run instead of being trusted."""
    parts = [x.strip().upper() for x in reply.split(',')]
    try:
        amp = float(parts[0])
        if len(parts) >= 5:
            freq = float(parts[4])
        elif len(parts) == 4:
            mult = {'HZ': 1.0, 'KHZ': 1e3, 'MHZ': 1e6, 'GHZ': 1e9}[parts[3]]
            freq = float(parts[2]) * mult
        else:
            raise ValueError
        unit = parts[1]                                   # the 5560A answers a leveled sine as '3.000E+00,VPP,0E+00,0,5.0E+04'
        if unit.endswith('PP'):
            unit = unit[:-2]
        if unit not in ('V', 'MV'):
            raise ValueError
        return amp * (1e-3 if unit == 'MV' else 1.0), freq
    except (ValueError, KeyError, IndexError):
        raise drivers.InstrumentError(f'Unexpected calibrator OUT? reply {reply!r}')


def hook_image(group, cal_text):
    """diagrams/hook_tds2000c_<5560A|5522A>_<GROUP>.png, else hook_tds2000c_<GROUP>.png; (path or None, names of what was looked for)."""
    cal = '5522A' if ('5522' in cal_text or '5520' in cal_text) else '5560A'
    names = [f'hook_tds2000c_{cal}_{group}.png', f'hook_tds2000c_{group}.png']
    for n in names:
        if (DIAGRAMS / n).is_file():
            return DIAGRAMS / n, names
    return None, names


# ======================================================================================================================
# uncertainty
# ======================================================================================================================
def uncertainty_parts(p, raw):
    """The number behind uncertainty_text: (value, unit, style) or None when the text is 'N/A'.  style: 'si' = uncertainty.format_value,
    'bwv' = the bandwidth amplitude uncertainty printed as 2 significant figures and the unit."""
    if p['stim'] == 'none' or p.get('passfail'):
        return None
    import report_pdf, uncertainty
    sc = report_pdf.scope()
    if sc is None:
        return None
    try:
        if p['kind'] == 'GAIN':
            ua = [abs(sc.oscilloscope('dcv', volts=abs(p[n]), impedance='1M')[0] or 0) / 100 * abs(p[n]) for n in ('vneg', 'vpos')]
            if all(ua):
                return math.hypot(*ua), 'V', 'si'
        if p['kind'] == 'BW':
            v, u, _ = sc.oscilloscope('bandwidth', volts_pp=raw.get('src_vpp', 3.0), frequency=raw.get('freq', 50e6))
            if v is not None:
                return (10 ** (v / 20) - 1) * raw.get('reading', 2.12), 'V', 'bwv'
    except Exception:
        return None
    return None


def format_uncertainty(parts):
    import uncertainty
    value, unit, style = parts
    if style == 'si':
        return uncertainty.format_value(value, unit)
    return f'{value:.2g} {unit}'


def uncertainty_text(p, raw):
    """Expanded uncertainty from the lab's A2LA scope (calibrator DC / level-sine CMC); 'N/A' where the scope has no entry (time marker,
    pass/fail points)."""
    parts = uncertainty_parts(p, raw)
    if parts is None:
        return 'N/A'
    try:
        return format_uncertainty(parts)
    except Exception:
        return 'N/A'


def tar_tur_fields(p, r):
    """dict(TAR, TUR) strings for one recorded point (r = its record), used only when the report asks for them.  TUR = tolerance /
    the uncertainty printed in the Uncertainty column, only when both are in the same unit (the DC gain points, volts) and the printed
    text is the one uncertainty_parts() gives now.  TAR is always blank: the gain test uses a difference of two DC outputs and every
    other test is a measurement, a leveled sine or a time marker, none of which has a matching specification row."""
    import tartur
    try:
        if p.get('passfail') or p.get('stim') == 'none':
            return dict(TAR='', TUR='')
        raw = r.get('raw', {})
        text = r.get('uncertainty') or uncertainty_text(p, raw)
        parts = uncertainty_parts(p, raw)
        u = uu = None
        if parts is not None and text != 'N/A' and format_uncertainty(parts) == text:
            import uncertainty
            u, uu = uncertainty.round_up(parts[0]), parts[1]
        return tartur.ratio_fields(tartur.from_values(tartur.half_width(p['low'], p['high']), p['unit'], None, None, u, uu))
    except Exception:
        return dict(TAR='', TUR='')


# ======================================================================================================================
# bench I/O
# ======================================================================================================================
class IO:
    """The oscilloscope (USB) and the calibrator."""

    def __init__(self, addrs, transports=None):
        self.log = drivers.CommandLog()
        self.addrs = addrs
        self.scope = self.cal = None
        t = transports or {}

        def tr(name, **kw):
            return t[name] if name in t else drivers.open_visa(to_visa(addrs[name]), timeout=30, **kw)
        try:
            self.scope = drivers.TektronixTDS2000C(tr('scope'), self.log, label='TDS2000C'); self.scope.connect()
            text = addrs.get('cal_model', CAL_CHOICES[0])
            if '5560' in text:
                self.cal = drivers.Fluke5560A(tr('cal', baud=int(addrs.get('cal_baud', 9600))), self.log, label='5560A')
            else:
                self.cal = drivers.Fluke5522AScope(tr('cal', baud=int(addrs.get('cal_baud', 9600))), self.log, label='5520A/5522A')
            self.cal.open(verify_model=True); self.cal.clear_status()
        except Exception:
            self.close(); raise
        self.ident = self.scope.idn
        self.is_5560 = '5560' in text

    def all_outputs_off(self):
        try:
            self.cal.standby_quiet()
        except Exception:
            pass

    def close(self):
        self.all_outputs_off()
        for inst in (self.scope, self.cal):
            if inst:
                try: inst.close()
                except Exception: pass
        self.save_log()

    def save_log(self):
        try:
            folder = Path.home() / '.calibration_suite'; folder.mkdir(parents=True, exist_ok=True)
            lines = self.log.lines()
            new, self._saved = lines[getattr(self, '_saved', 0):], len(lines)      # only what has not been written yet
            if not new:
                return
            with open(folder / 'command_log.txt', 'a', encoding='utf-8') as f:
                f.write(f'--- {datetime.now().isoformat(timespec="seconds")}  TDS2000C session\n' + '\n'.join(new) + '\n')
        except OSError:
            pass


def to_visa(text):
    t = text.strip()
    if '::' in t or t.upper().startswith(('ASRL', 'USB', 'GPIB', 'TCPIP')):
        return t
    t = t.upper().replace('COM', '')
    if not t.isdigit():
        raise ValueError('Enter a COM port (COM9) or a full VISA address (USB0::...::INSTR, GPIB0::6::INSTR).')
    return f'ASRL{int(t)}::INSTR'


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
        self._sine = None                       # (vpp, Hz) currently output by the calibrator, None when unknown or in standby
        self._start = {}                        # source level that worked for a trigger stage on an earlier channel

    # ---- plumbing ------------------------------------------------------------------------------------------------------------
    def check(self):
        if self.app.stop:
            raise Stopped()

    def ask(self, title, heading, steps, facts=None, caution=None, ok='Continue', image=None):
        self.check()
        if not self.app.request('ask', dict(title=title, heading=heading, steps=steps, facts=facts, caution=caution, ok=ok, image=image)):
            raise Stopped()

    def status(self, text):
        self.app.post('status', text)

    def wire(self, key, title, steps, group=None, facts=None, caution=None):
        """Prompt only when the physical setup changes. `group` picks the hook-up diagram."""
        if key == self._wired:
            return
        self.io.all_outputs_off()
        image = None
        if group:
            path, names = hook_image(group, self.app.cal_text())
            image = str(path) if path else None
            if path is None:
                facts = (facts or []) + [('Diagram', 'not found (' + names[0] + '); follow the text steps')]
        self.ask(title, title, steps, facts, caution, ok='Connected - continue', image=image)
        self._wired = key

    def fresh_scope(self, key):
        """Default setup once per group; later points only change scale etc."""
        if self._scope_ctx != key:
            self.io.scope.default_setup()
            self._scope_ctx = key

    def run_point(self, p):
        fn = getattr(self, 'do_' + p['kind'].lower(), None)
        if fn is None:
            raise Skip(f'no executor for {p["kind"]}')
        try:
            return fn(p)
        finally:
            self._sine = None
            self.io.all_outputs_off()
            if p['stim'] == 'cal':
                self.io.cal.standby()           # confirmed: SafetyError if the calibrator does not report standby

    # ---- calibrator helpers ----------------------------------------------------------------------------------------------------
    def dc_source(self):
        cal = self.io.cal
        cal.standby_quiet()
        cal.drain_errors()                      # an error left from earlier is never blamed on this setup (it is in the command log)
        if self.io.is_5560:
            # The 5560A rejects 'OUT_IMP 1M' (-117, seen on the bench) and answers OUT_IMP? with Z1M, so the impedance is only READ here:
            # SCOPE DCV output is 1 MOhm and the reply must say so. (Fluke5560A.select_scope_dcv is shared and left unchanged.)
            cal.write('SCOPE DCV')
            cal.check_error('SCOPE DCV')
            function = cal.query('FUNC?').strip().upper()
            mode = cal.query('SCOPE?').strip().upper()
            if function != 'SDCV' or mode != 'VOLT':
                raise drivers.InstrumentError(f'5560A did not select SCOPE DCV: FUNC?={function!r}, SCOPE?={mode!r}')
            self.ensure_imp_5560('1M')
        else:
            cal.select_scope_dcv('1M')
            cal.check_error('SCOPE VOLT / OUT_IMP Z1M')   # 5520A/5522A path: SCOPE VOLT and OUT_IMP Z1M are in the 5522A Operators Manual ch. 10

    def apply_dc(self, volts, settle=2.0):
        cal = self.io.cal
        cal.set_dc_volts(volts)                 # set and read back
        cal.check_error(f'{volts:g} V')
        cal.operate()                           # OPER, confirmed
        pause(settle)

    def select_levsine(self):
        cal = self.io.cal
        cal.standby_quiet()
        self._sine = None
        cal.drain_errors()
        cal.select_scope_levsine()
        cal.check_error('SCOPE LEVSINE')
        mode = cal.query('SCOPE?').strip().upper()
        if 'LEV' not in mode:
            raise drivers.InstrumentError(f'Calibrator did not confirm leveled sine: SCOPE?={mode!r}')
        if self.io.is_5560:
            self.ensure_imp_5560('50')          # 'OUT_IMP 50' is rejected (-117) on the 5560A: read first, write Z50 only if needed
        else:
            cal.write('OUT_IMP Z50')            # 5522A manual p. 10-31: the argument is Z50 / Z1M
            cal.check_error('OUT_IMP Z50')

    def ensure_imp_5560(self, want):
        """5560A SCOPE output impedance: read OUT_IMP?; only if it is not already `want` ('1M' or '50') write 'OUT_IMP Z1M' / 'Z50' ONCE (argument form
        taken from the reply 'Z1M'; UNVERIFIED), check the error queue and read back. Never repeated."""
        cal = self.io.cal
        ok = (lambda r: '1M' in r or r.startswith('1000000')) if want == '1M' else (lambda r: r.endswith('Z50') or r.startswith(('50', 'Z50')))
        imp = cal.query('OUT_IMP?').strip().upper()
        if not ok(imp):
            cal.write(f'OUT_IMP Z{want}')
            cal.check_error(f'OUT_IMP Z{want}')
            imp = cal.query('OUT_IMP?').strip().upper()
            if not ok(imp):
                raise drivers.InstrumentError(f'5560A SCOPE output impedance is {imp!r}, not {want}; set it on the calibrator front panel')
        cal.check_error('OUT_IMP?')

    def set_sine(self, vpp, hz, settle=2.0):
        """Set amplitude and frequency, read OUT? back and compare, then operate. A rejected or mismatched setting stops the run."""
        if vpp > SOURCE_LIMITS['vpp_max'] or hz < SOURCE_LIMITS['f_min']:
            raise drivers.InstrumentError(f'{vpp:g} V p-p at {hz:g} Hz is outside the leveled-sine range used here')
        cal = self.io.cal
        if self._sine == (vpp, hz) and cal.is_operating():
            return vpp                          # already output and operating at exactly this setting: no rewrite, no settling wait
        self._sine = None
        cal.set_levsine(vpp, hz)
        cal.check_error(f'levsine {vpp:g} V p-p {hz:g} Hz')
        amp, freq = parse_out_reply(cal.query('OUT?'))
        # The calibrator keeps limited digits (it answered 1.19 V for 1.19048 V at 200 MHz), so the amplitude must agree within its resolution
        # (1 % or 2 mV); the frequency stays tight. The amplitude it reports is returned and used as the real source level.
        if not (math.isclose(amp, vpp, rel_tol=1e-2, abs_tol=2e-3) and math.isclose(freq, hz, rel_tol=1e-4)):
            raise drivers.InstrumentError(f'Calibrator setting mismatch: asked {vpp:g} V p-p, {hz:g} Hz; OUT? reports {amp:g} V, {freq:g} Hz')
        cal.operate()
        pause(settle)
        self._sine = (amp, hz)
        return amp

    def tune_sine(self, ch, hz, start_vpp, target_pp, low=None, high=None, tol=0.05, tries=5, count=16):
        """Closed loop: change the calibrator level until the scope's own Pk-Pk reading is in [low, high] (default target +/- tol).
        Each change is a new, read-back setting (not a retry). Returns (source vpp, measured)."""
        low = target_pp * (1 - tol) if low is None else low
        high = target_pp * (1 + tol) if high is None else high
        vpp, scope = start_vpp, self.io.scope
        for _ in range(tries):
            self.check()
            vpp = self.set_sine(vpp, hz)            # the level the calibrator reports (it rounds to its resolution)
            measured = scope.measure('PK2pk', ch, count=count)
            if low <= measured <= high:
                return vpp, measured
            nxt = vpp * target_pp / max(measured, 1e-9)
            if nxt > SOURCE_LIMITS['vpp_max'] or nxt < 0.5 * vpp / 10:
                raise drivers.InstrumentError(
                    f'CH{ch} reads {measured:.4g} V p-p with the calibrator at {vpp:g} V p-p, {hz:g} Hz (wanted {low:g} to {high:g} V). '
                    f'Reaching it would need {nxt:g} V p-p, so the run stops: check the cable/terminator, the scope channel, and that the calibrator output is on')
            vpp = nxt
        raise drivers.InstrumentError(f'Could not set the scope reading to {low:g}-{high:g} V p-p at {hz:g} Hz (last: {measured:g} V from {vpp:g} V p-p source)')

    # ---- self test / self calibration -----------------------------------------------------------------------------------------------
    def do_selftest(self, p):
        self.wire(('SELF',), 'Self test', [('Warm up', 'The oscilloscope must have been operating continuously for twenty minutes within its operating temperature range (p. 4-3).'),
                  ('Disconnect', 'No test equipment or hook-up is needed. Check the screen shows no error message.')])
        ok, log = self.io.scope.run_self_test()
        return (1.0 if ok else 0.0), dict(log=log[:300])

    def do_selfcal(self, p):
        self.wire(('SELFCAL',), 'Self calibration', [('Disconnect', 'Disconnect all probes and cables from every channel input (p. 4-3).'),
                  ('Wait', 'The routine takes about a minute; the oscilloscope does not answer commands meanwhile.')])
        self.status('Self calibration running (about a minute) ...')
        ok, text = self.io.scope.self_cal()
        return (1.0 if ok else 0.0), dict(result=text)

    # ---- DC gain -------------------------------------------------------------------------------------------------------------------------
    def do_gain(self, p):
        ch = p['ch']
        self.wire(('DCV', ch), f'DC gain - CH{ch}', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Calibrator SCOPE output to CH{ch} with the BNC cable (SCOPE volts, 1 MOhm output impedance). No terminator.')],
                  group='DCV')
        s = self.io.scope
        if self._scope_ctx != ('GAIN', ch):
            s.default_setup(); self._scope_ctx = ('GAIN', ch)
            s.select_only(ch)
            s.acquire_mode('AVErage', 16)
            s.measure_setup('MEAN', ch)
        s.channel(ch, vscale=p['vscale'], position=0.0, probe=1)
        s.check_errors('DC gain setup')
        self.dc_source()
        self.apply_dc(p['vpos']); vpos_m = s.measure('MEAN', ch)
        self.apply_dc(p['vneg']); vneg_m = s.measure('MEAN', ch)
        self.io.cal.standby_quiet()
        return vpos_m - vneg_m, dict(vpos_set=p['vpos'], vneg_set=p['vneg'], vpos_meas=vpos_m, vneg_meas=vneg_m, vdiff_expected=p['vdiff'])

    # ---- bandwidth -----------------------------------------------------------------------------------------------------------------------
    def do_bw(self, p):
        ch = p['ch']
        freq = self.cfg.info['bw_test_hz']
        self.wire(('LEV', ch), f'Bandwidth - CH{ch}', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Calibrator SCOPE output (leveled sine, 50 Ohm) to CH{ch} through the 50 Ohm BNC cable and the 50 Ohm feedthrough terminator at the scope input.')],
                  group='LEVSINE')
        s = self.io.scope
        s.default_setup(); self._scope_ctx = ('BW', ch)
        s.select_only(ch)
        s.channel(ch, vscale=p['vscale'], position=0.0, probe=1)
        s.acquire_mode('AVErage', 16)
        s.trigger_edge(f'CH{ch}', 'RISe', 'AUTO', coupling='NOISErej')
        s.timebase(p['hscale_ref'])
        s.check_errors('bandwidth setup')
        self.select_levsine()
        src, vin = self.tune_sine(ch, p['ref_hz'], p['ref_target'], p['ref_target'], low=p['ref_low'], high=p['ref_high'])
        s.timebase(p['hscale'])
        self.set_sine(src, freq)
        vbw = s.measure('PK2pk', ch)
        self.io.cal.standby_quiet()
        return vbw, dict(src_vpp=src, vin_pp=vin, vbw_pp=vbw, freq=freq, ref_hz=p['ref_hz'])

    # ---- sample rate / delay time -----------------------------------------------------------------------------------------------------------
    def do_timebase(self, p):
        self.wire(('MARK',), 'Sample rate and delay time accuracy', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', 'Calibrator SCOPE output (time marker) to CH1 through the BNC cable and the 50 Ohm feedthrough terminator at the scope input.')],
                  group='MARKER')
        s, cal = self.io.scope, self.io.cal
        s.default_setup(); self._scope_ctx = ('TB',)
        s.select_only(1)
        s.channel(1, vscale=p['vscale'], position=0.0, probe=1)
        s.acquire_mode('SAMple')
        s.trigger_edge('CH1', 'RISe', 'AUTO', coupling='DC')
        s.timebase(p['hscale_set'])
        cal.standby_quiet(); cal.select_scope_marker(); cal.set_marker_period(p['period']); cal.operate()
        pause(2.0)
        s.set_level_50()                                               # step 6
        s.trigger_mode('NORMal')
        s.wait_acquisitions(2)
        times, volts = s.waveform(1)                                   # step 7: centre the marker vertically
        mid = (max(volts) + min(volts)) / 2
        s.position(1, -mid / p['vscale'])
        s.horizontal_position(p['delay'])                              # step 8
        s.timebase(p['hscale_meas'])                                   # step 9
        pause(1.0)
        s.wait_acquisitions(2)
        edges, centres = [], []
        for _ in range(5):                                             # step 10, measured instead of read by eye
            times, volts = s.waveform(1)
            centres.append(times[len(times) // 2])
            found = edge_times(times, volts, 'RISe')
            if not found:                   # the edge is off screen: far outside the +/-2 div limit, so it is a FAIL, not a program error
                cal.standby_quiet()
                return 99.0, dict(edge_missing=True, delay_s=p['delay'], note='no marker edge inside the 10 div record')
            edges.append(min(found, key=lambda t: abs(t - p['delay'])))
            pause(0.2)
        one_div = p['hscale_meas']
        if abs(sum(centres) / len(centres) - p['delay']) > 1.5 * one_div:
            raise drivers.InstrumentError(f'The waveform time axis is not what the procedure expects (record centre {sum(centres) / len(centres):.9g} s, '
                                          f'expected near {p["delay"]:g} s): check HORizontal:MAIn:POSition and WFMPre:XZEro on this firmware')
        mean_edge = sum(edges) / len(edges)
        err_div = (mean_edge - p['delay']) / one_div
        cal.standby_quiet()
        return err_div, dict(edge_s=mean_edge, spread_s=max(edges) - min(edges), delay_s=p['delay'], ppm=(mean_edge - p['delay']) / p['delay'] * 1e6)

    # ---- trigger sensitivity ---------------------------------------------------------------------------------------------------------------------
    def check_stable(self, wave_ch, freq, slope, hscale, strict_level=True):
        """Engine criteria for 'stable trigger' (the manual says only 'check that triggering is stable'):
        trigger mode Normal, Set To 50 %, acquisitions keep completing, and the edge position in STABLE_CAPTURES successive records
        stays within STABLE_JITTER_PERIODS of a period.  Returns (stable, details)."""
        s = self.io.scope
        s.trigger_mode('NORMal')
        note = ''
        if strict_level:
            s.set_level_50()
        else:
            try:
                s.set_level_50()
            except drivers.InstrumentError as exc:
                note = str(exc)
        pause(1.0)
        states = [s.trigger_state() for _ in range(5)]
        n0 = s.num_acq(); pause(1.0); n1 = s.num_acq()
        locked = (n1 - n0) >= STABLE_MIN_ACQ
        crossings = []
        ppc = 2500.0 / max(freq * 10 * hscale, 1e-12)          # record points per signal cycle (10 divisions on screen)
        for times, volts in s.waveform_burst(wave_ch, STABLE_CAPTURES, half_points=math.ceil(ppc) + 2):    # +/- one cycle around the trigger point
            found = edge_times(times, volts, slope)
            if found:
                crossings.append(min(found, key=abs))
        period = 1.0 / freq
        spread = (max(crossings) - min(crossings)) if len(crossings) == STABLE_CAPTURES else float('inf')
        stable = locked and spread <= STABLE_JITTER_PERIODS * period
        return stable, dict(freq=freq, slope=slope, acquisitions=n1 - n0, states=states, spread_periods=(spread / period if math.isfinite(spread) else None), level_note=note)

    def resolve_freq(self, tag, last):
        return {'10M': 10e6, 'F': self.cfg.info['trig_hz'], '200M': 200e6}.get(tag, last)

    def do_trig(self, p):
        ch = p['ch']
        self.wire(('TRIGCH', ch), f'Edge trigger - CH{ch}', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', f'Calibrator SCOPE output (leveled sine, 50 Ohm) to CH{ch} through the 50 Ohm BNC cable and the 50 Ohm feedthrough terminator at the scope input.')],
                  group='LEVSINE')
        s = self.io.scope
        s.default_setup(); self._scope_ctx = ('TRIG', ch)
        s.select_only(ch)
        s.channel(ch, vscale=p['vscale'], position=0.0, probe=1)
        s.acquire_mode('SAMple')
        s.trigger_edge(f'CH{ch}', 'RISe', 'NORMal', coupling='DC')
        s.check_errors('trigger setup')
        self.select_levsine()
        results, last_f, last_pp, src = [], None, None, 1.0
        for st in p['stages']:
            if st.get('models') and self.cfg.model not in st['models']:
                continue
            self.check()
            last_f = self.resolve_freq(st['freq'], last_f)
            last_pp = last_pp if st['meas_vpp'] == 'LAST' else st['meas_vpp']
            s.timebase(st['hscale'])
            s.trigger_edge(f'CH{ch}', st['slope'], 'AUTO', coupling='DC')        # measure the amplitude with the scope free-running
            key = (st['step'], last_f, last_pp)
            start = src if st['meas_vpp'] == 'LAST' else self._start.get(key, last_pp)
            src, meas = self.tune_sine(ch, last_f, start, last_pp, tol=0.10, count=3)     # Sample mode: no averaging to wait for
            self._start[key] = src
            ok, detail = self.check_stable(ch, last_f, st['slope'], st['hscale'])
            results.append(dict(step=st['step'], stable=ok, measured_vpp=meas, source_vpp=src, **detail))
        self.io.cal.standby_quiet()
        return (1.0 if all(r['stable'] for r in results) else 0.0), dict(stages=results)

    def do_exttrig(self, p):
        self.wire(('EXT',), 'External edge trigger', [('Disconnect', 'Remove other cables from the oscilloscope inputs.'),
                  ('Connect', 'As the figure on p. 4-9: calibrator SCOPE output to the power splitter; one splitter output to CH1 and the other to EXT TRIG, '
                              'each through a 50 Ohm feedthrough terminator (use equal-length cables).')], group='EXTTRIG')
        s = self.io.scope
        s.default_setup(); self._scope_ctx = ('EXT',)
        s.select_only(1)
        s.channel(1, vscale=p['vscale'], position=0.0, probe=1)
        s.acquire_mode('SAMple')
        s.trigger_edge('EXT', 'RISe', 'NORMal', coupling='DC')
        s.check_errors('external trigger setup')
        self.select_levsine()
        results, last_f, src = [], None, 0.3
        for st in p['stages']:
            if st.get('models') and self.cfg.model not in st['models']:
                continue
            self.check()
            last_f = self.resolve_freq(st['freq'], last_f)
            s.timebase(st['hscale'])
            s.trigger_edge('EXT', st['slope'], 'AUTO', coupling='DC')
            if 'ch1_vpp' in st:
                key = (st['step'], last_f)
                src, meas = self.tune_sine(1, last_f, self._start.get(key, st['ch1_vpp'] * 1.5), st['ch1_vpp'], tol=0.10, count=3)
                self._start[key] = src
            else:
                src = src if st.get('src_vpp') == 'LAST' else st['src_vpp']
                self.set_sine(src, last_f)
                meas = s.measure('PK2pk', 1, count=3)
            row = dict(step=st['step'], source_vpp=src, ch1_vpp=meas, freq=last_f)
            if st['check']:
                ok, detail = self.check_stable(1, last_f, st['slope'], st['hscale'], strict_level=False)
                row.update(stable=ok, **detail)
            else:
                row['stable'] = True
            results.append(row)
        self.io.cal.standby_quiet()
        return (1.0 if all(r['stable'] for r in results) else 0.0), dict(stages=results)

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
        root.title('Tektronix TDS2000C | Performance Verification' + (' [DEMO]' if demo else ''))
        ui.fit_window(root, 1380, 880, min_w=900, min_h=680)
        self.settings = ui.Settings('TDS2000C')
        g = self.settings.get
        self.asset, self.serial = tk.StringVar(), tk.StringVar()
        self.v_model = tk.StringVar(value=g('model', '2024C'))
        self.addr = {k: tk.StringVar(value=g(k, d)) for k, d in (('scope', ''), ('cal', 'COM9'), ('cal_baud', '9600'), ('cal_model', CAL_CHOICES[0]))}
        self.status = tk.StringVar()
        self.detail = tk.StringVar(value='Select a test point to see its limits and setup.')
        self.show_section = tk.StringVar(value='All sections')
        self.show_status = tk.StringVar(value='All points')
        self._build_ui()
        self.on_config(save=False)
        self.status.set('DEMO MODE: no commands are sent to any instrument.' if demo else
                        'Step 1: instrument ID and model. Step 2: addresses, then Test Connections. Step 3: Run All Pending.')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.bind('<Control-s>', lambda _e: self.save())
        import labregistry
        labregistry.attach(root, self.asset, self.serial, self.status.set)
        self.root.after(50, self._pump)

    def cal_text(self):
        return self.addr['cal_model'].get()

    def read_cfg(self):
        self.cfg = Config(self.v_model.get().replace('TDS', ''))
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

    # ---- layout ---------------------------------------------------------------------------------------------------------------------
    def _build_ui(self):
        root = self.root
        sh = self.shell = ui_shell.Shell(root, 'Tektronix TDS2000C / TDS1000C-EDU  -  Performance Verification',
                                         f'{SPEC["source"]["document"]}  |  {len(POINTS)} points in the spec',
                                         demo=self.demo, on_section=self.pick_section, version='spec v1')
        self.status = sh.status_var
        self.conn_pill = sh.add_chip('Not connected', 'neutral')
        sh.build_identity(self.asset, self.serial)
        self.build_mode_segment(sh.strip, notice_holder=sh.notice_holder)
        self.summary = sh.build_progress()
        if self.demo: sh.notice('Results are generated by the program and are NOT calibration evidence. Reports are marked as demo data.', 'warn', title='Demo mode')
        else: sh.notice('The program stops and asks you to confirm every cable, terminator and splitter change before the next point. '
                        'Stay at the bench; the calibrator is returned to STANDBY after every point.', 'info')

        d = sh.drawer_body; d.columnconfigure(1, weight=1)
        ttk.Label(d, text='Model').grid(row=0, column=0, sticky='w', pady=4)
        m = ttk.Combobox(d, textvariable=self.v_model, values=['TDS' + x for x in MODELS], width=14, state='readonly'); m.grid(row=0, column=1, padx=(10, 0), pady=4, sticky='w')
        m.set('TDS' + self.v_model.get().replace('TDS', ''))
        self.btn_read_model = ttk.Button(d, text='Read model from scope', command=self.read_model); self.btn_read_model.grid(row=1, column=0, columnspan=2, sticky='w', pady=(4, 0))
        self.cfg_widgets = [m]
        m.bind('<<ComboboxSelected>>', lambda _e: self.on_config())
        ttk.Separator(d).grid(row=2, column=0, columnspan=2, sticky='ew', pady=(12, 10))
        self.addr_boxes = {}
        for i, (key, label) in enumerate([('scope', 'TDS2000C (USB)'), ('cal', 'Calibrator (COM or GPIB)')]):
            ttk.Label(d, text=label).grid(row=3 + i, column=0, sticky='w', pady=4)
            cb = ttk.Combobox(d, textvariable=self.addr[key], state='normal', width=34); cb.grid(row=3 + i, column=1, sticky='ew', padx=(10, 0), pady=4)
            self.addr_boxes[key] = cb
        ttk.Label(d, text='Calibrator').grid(row=5, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.addr['cal_model'], values=CAL_CHOICES, width=14, state='readonly').grid(row=5, column=1, sticky='w', padx=(10, 0), pady=4)
        ttk.Label(d, text='Calibrator baud').grid(row=6, column=0, sticky='w', pady=4)
        ttk.Combobox(d, textvariable=self.addr['cal_baud'], values=['9600', '19200', '4800', '2400', '1200'], width=9, state='readonly').grid(row=6, column=1, sticky='w', padx=(10, 0), pady=4)
        ttk.Label(d, text='The oscilloscope is connected by USB. All outputs (DC volts, leveled sine, time marker) come from the calibrator scope option.',
                  style='Muted.TLabel', wraplength=ui.px(340), justify='left').grid(row=7, column=0, columnspan=2, sticky='w', pady=(8, 0))
        btns = sh.drawer_footer
        self.btn_find = ttk.Button(btns, text='Find instruments', command=self.find_instruments); self.btn_find.pack(side='left', padx=(0, 8))
        self.btn_test = ttk.Button(btns, text='Test connections', command=self.test_connections, style='Accent.TButton'); self.btn_test.pack(side='left')

        self.btn_run = sh.add_action('▶  Run All Pending', self.run_all, accent=True, short='▶  Run')
        self.btn_section = sh.add_action('Run Shown Section', self.run_section, short='Section')
        self.btn_rerun = sh.add_action('Rerun Selected', self.rerun, short='Rerun')
        self.btn_stop = sh.add_action('■  Stop', self.request_stop, danger=True, short='■ Stop', state='disabled')
        sh.add_action('Export Report (PDF)', self.export_pdf, side='right', short='PDF')
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

    def on_config(self, save=True):
        self.v_model.set(self.v_model.get().replace('TDS', ''))
        self.read_cfg()
        if save:
            self.settings.set('model', self.v_model.get()); self.settings.save()
        self.refresh()

    def read_model(self):
        if self.demo:
            messagebox.showinfo('Demo mode', 'Demo mode uses no hardware.'); return
        if self.io is None: self.test_connections()
        if self.io is None: return
        model = self.io.scope.model
        if model in MODELS:
            self.v_model.set(model); self.on_config()
            messagebox.showinfo('Model read', f'The oscilloscope reports TDS{model} ({self.io.scope.channels} channels).')
        else:
            messagebox.showwarning('Model', f'Could not recognise a model in: {self.io.scope.idn}\nChoose it in the Model box.')

    # ---- table ---------------------------------------------------------------------------------------------------------------------------
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
        fmt = (lambda v: fmt_plain(v, 5) + (' ' + unit if unit else '')) if unit in PLAIN_UNITS else (lambda v: ui.si(v, unit))
        cells, tags = self.shell_cells(key, p['nominal'], p['low'], p['high'], unit, fmt=fmt)
        cells = list(cells)
        if res == 'SKIP': cells[4:7] = ['', '', '']
        return (p['id'], p['desc'], *cells), tags

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
        raw = self.results.get(str(p['id']), {}).get('raw')
        extra = ('  |  ' + p['note']) if p.get('note') else ''
        work = ''
        if raw:
            work = '\nWorksheet: ' + ', '.join(f'{k} = {v:.6g}' if isinstance(v, float) else f'{k} = {v}' for k, v in raw.items() if not isinstance(v, (list, dict)))
        both = ('\n' + self.found_left_text(p)) if self.found_left_text(p) else ''
        self.detail.set(f'{p["desc"]}\nLimits: {lo} to {hi} {unit}  |  Stimulus: {"calibrator scope option" if p["stim"] == "cal" else "none"}  |  Manual page {SECTION_PAGE[p["section"]]}{extra}{work}{both}')

    # ---- connections ---------------------------------------------------------------------------------------------------------------------------
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
        self.status.set('Connected: ' + self.io.ident + '. Calibrator in standby.')
        messagebox.showinfo('Connected', f'Oscilloscope: {self.io.ident}\nCalibrator: {self.io.cal.idn}')

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

    # ---- thread <-> UI ------------------------------------------------------------------------------------------------------------------------------
    def post(self, kind, payload=None):
        self.q.put((kind, payload, None))

    def request(self, kind, payload):
        """Called on the worker thread: ask the main thread something and wait for the answer."""
        box = dict(ev=threading.Event(), value=None)
        self.q.put((kind, payload, box))
        while not box['ev'].wait(0.1):
            if self.stop:
                raise Stopped()
        return box['value']

    def _pump(self):
        try:
            while True:
                kind, payload, box = self.q.get_nowait()
                if kind == 'status': self.status.set(payload)
                elif kind == 'row': self._update_row(POINTS[payload - 1])
                elif kind == 'done': self._finished(payload)
                elif kind == 'ask':
                    box['value'] = ui.confirm_steps(self.root, payload['title'], payload['heading'], payload['steps'], facts=payload['facts'],
                                                    caution=payload['caution'], ok=payload['ok'], image=payload.get('image'))
                    box['ev'].set()
        except queue.Empty:
            pass
        self.root.after(50, self._pump)

    # ---- running ------------------------------------------------------------------------------------------------------------------------------------------
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
                    self.results[str(p['id'])] = dict(result='SKIP', reason=str(s), timestamp=datetime.now().isoformat(timespec='seconds'), data=self.mode_label)
                    self.post('row', p['id'])
        except Stopped:
            error = 'stopped'
        except BaseException as exc:
            error = exc
        finally:
            try: self.io.all_outputs_off()
            except Exception: pass
            try: self.io.save_log()          # the log is on disk after every run or error, not only when the window closes
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

    # ---- files ----------------------------------------------------------------------------------------------------------------------------------------------
    def _checkpoint_path(self):
        name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        return appdata.progress_path(f'TDS{self.cfg.model}_{name}_checkpoint.json')

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
        self.v_model.set(data.get('config', {}).get('model', self.v_model.get()))
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
            return dict(Section=sec, Description=p['desc'], Nominal='Pass', **{'Tolerance -': 'N/A', 'Tolerance +': 'N/A'}, UOM='',
                        **{'As Found': 'Pass' if not failed else 'Fail'}, OOT='OOT' if failed else '', **{'As Left': 'Same'}, Uncertainty='N/A')
        if p['unit'] in PLAIN_UNITS:
            nom, lo, hi, rd, unit = display_row(p, r['reading'])
            return {'Section': sec, 'Description': p['desc'], 'Nominal': nom, 'Tolerance -': lo, 'Tolerance +': hi, 'UOM': unit, 'As Found': rd,
                    'OOT': 'OOT' if failed else '', 'As Left': 'Same', 'Uncertainty': unc}
        row = report_pdf.cert_row(p['desc'], p['nominal'], p['low'] if p['low'] is not None else float('nan'), p['high'] if p['high'] is not None else float('nan'),
                                  p['unit'], r['reading'], failed, section=sec, uncertainty=unc)
        if p['low'] is None: row['Tolerance -'] = 'N/A'
        if p['high'] is None: row['Tolerance +'] = 'N/A'
        if p['low'] is None or p['high'] is None:
            row['Nominal'] = ('<= ' if p['high'] is not None else '>= ') + row['Tolerance +' if p['high'] is not None else 'Tolerance -'] + ' ' + row['UOM']
        return row

    def certificate_pairs(self):
        """(point, report row): As Found for every recorded point; As Left where it was measured again after an adjustment, else 'Same'."""
        pairs = []
        for p in POINTS:
            if not self.cfg.applies(p): continue
            row = self.found_left_row(p, lambda r: self.certificate_row(p, r))
            if row: pairs.append((p, row))
        return pairs

    def certificate_rows(self):
        return [row for _p, row in self.certificate_pairs()]

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
        if not rows: messagebox.showinfo('No results', 'No recorded results to export yet.'); return
        try: import report_pdf, report_dialog
        except ImportError as exc: messagebox.showerror('Report export', str(exc)); return
        details = report_dialog.ask_details(self.root, 'Tektronix TDS2000C performance verification')
        if details is None: return
        asset = ''.join(c if c.isalnum() or c in '-_' else '_' for c in self.asset.get()) or 'UNASSIGNED'
        path = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF report', '*.pdf')], initialfile=ui.report_filename(asset))
        if not path: return
        demo = self.any_synthetic()
        skipped = sum(1 for v in self.found.values() if v.get('result') == 'SKIP')
        note = ('Uncertainty: DC points use the laboratory A2LA scope (calibrator CMC); points the scope does not cover show N/A.'
                + (f' {skipped} point(s) were skipped.' if skipped else ''))
        try:
            if report_pdf.details_tar_tur(details):
                rows = report_pdf.apply_tar_tur(rows, report_pdf.details_tar_tur(details), [self.tar_tur_for(p) for p, _row in pairs])
            report_pdf.write_calibration_pdf(path, rows, header=[('Instrument', f'Tektronix TDS{self.cfg.model}'), ('Instrument ID', self.asset.get()), ('Serial', self.serial.get()),
                                                                 ('Source', 'TDS2000C / TDS1000C-EDU Service Manual 077-0446-01, Chapter 4')],
                                             demo=demo, details=details, footer_note=note, title='Calibration Data')
        except ImportError:
            messagebox.showerror('PDF export dependency', 'Install the PDF package with:  py -m pip install reportlab'); return
        except Exception as exc:
            messagebox.showerror('PDF export error', str(exc)); return
        self.status.set(f'Exported {len(rows)} rows: {path}')

    def on_close(self):
        if self.busy and not messagebox.askyesno('Active run', 'A point may be active. Stop and close?'): return
        self.stop = True; self._save_addrs(); self.disconnect(); self.root.destroy()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    root = tk.Tk()
    App(root, demo='--demo' in argv)
    root.mainloop()
